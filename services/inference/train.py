#!/usr/bin/env python3
"""Fine-tune the small flood U-Net on the hand-labeled Sen1Floods11 chips.

Uses CUDA when PyTorch can see an NVIDIA GPU. Trains on the full 512×512 chip
with flips and quarter-turns, and a sum of binary cross-entropy and Dice.
Spain and Ghana stay out of training, whole events, so chips from the same
flood cannot leak into the score. The original 11 held-out chips stay out as
well, so the new IoU can be compared with the published 0.61 on the same chips.

The live checkpoint is replaced only when the new weights beat that checkpoint
on both sets and also beat the VH threshold on the held-out events.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import tifffile
import torch
import torch.nn.functional as F

from segment import FloodUNet, iou_score, normalize_db, threshold_probability, torch_device

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CHIPS = ROOT / "data" / "metadata" / "chips.geojson"
METADATA = ROOT / "data" / "metadata" / "Sen1Floods11_Metadata.geojson"
SPLIT_OUT = ROOT / "data" / "metadata" / "train_split_events.json"
WEIGHTS = Path(__file__).resolve().parent / "weights" / "flood_unet.pt"
CANDIDATE = Path(__file__).resolve().parent / "weights" / "flood_unet_candidate.pt"
CARD = Path(__file__).resolve().parent / "model_card.json"

# Whole floods. Spain is the event closest to the vigía; Ghana is a second
# continent so the score is not a single flood.
HOLDOUT_EVENTS = ("Spain", "Ghana")
LEGACY_HELDOUT = [
    "Bolivia_242570",
    "Ghana_319168",
    "India_1068117",
    "Mekong_16233",
    "Nigeria_598959",
    "Pakistan_1036366",
    "Paraguay_896458",
    "Somalia_12849",
    "Spain_3285448",
    "Sri-Lanka_847275",
    "USA_366607",
]
LOCATION_TO_PREFIX = {
    "Bolivia": "Bolivia",
    "Ghana": "Ghana",
    "India": "India",
    "Cambodia": "Mekong",
    "Nigeria": "Nigeria",
    "Pakistan": "Pakistan",
    "Paraguay": "Paraguay",
    "Somalia": "Somalia",
    "Spain": "Spain",
    "Sri-Lanka": "Sri-Lanka",
    "USA": "USA",
}

EPOCHS = 40
PATIENCE = 8
BATCH = 4
LR = 1e-4
SEED = 11
PREVIOUS_REPORTED_IOU = 0.6097


def event_thresholds() -> dict[str, float]:
    meta = json.loads(METADATA.read_text())
    thresholds: dict[str, float] = {}
    for feature in meta["features"]:
        props = feature["properties"]
        prefix = LOCATION_TO_PREFIX.get(props["location"])
        if prefix is not None:
            thresholds[prefix] = float(props["VH_thresh"])
    missing = [name for name in HOLDOUT_EVENTS if name not in thresholds]
    if missing:
        raise RuntimeError(f"Sin umbral VH para {missing}.")
    return thresholds


def load_chip(chip_id: str) -> tuple[np.ndarray, np.ndarray]:
    image_path = RAW / f"{chip_id}_S1Hand.tif"
    label_path = RAW / f"{chip_id}_LabelHand.tif"
    if not image_path.exists() or not label_path.exists():
        raise FileNotFoundError(f"Falta {chip_id} en {RAW}.")
    image = np.squeeze(tifffile.imread(image_path)).astype(np.float32)
    label = np.squeeze(tifffile.imread(label_path)).astype(np.int16)
    if image.shape[0] != 2:
        image = np.moveaxis(image, -1, 0)
    if image.shape != (2, 512, 512) or label.shape != (512, 512):
        raise ValueError(f"{chip_id} no es 512×512 (imagen {image.shape}, etiqueta {label.shape}).")
    image = np.nan_to_num(image, nan=-25.0, posinf=0.0, neginf=-40.0)
    return np.ascontiguousarray(image), np.ascontiguousarray(label)


def augment(image: np.ndarray, label: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    turns = random.randint(0, 3)
    if turns:
        image = np.rot90(image, turns, axes=(1, 2))
        label = np.rot90(label, turns, axes=(0, 1))
    if random.random() < 0.5:
        image = np.flip(image, axis=2)
        label = np.flip(label, axis=1)
    if random.random() < 0.5:
        image = np.flip(image, axis=1)
        label = np.flip(label, axis=0)
    return np.ascontiguousarray(image), np.ascontiguousarray(label)


def dice_bce(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor | None:
    valid = labels != -1
    if int(valid.sum()) == 0:
        return None
    target = (labels == 1).float()
    bce = F.binary_cross_entropy_with_logits(logits[valid], target[valid])
    prob = torch.sigmoid(logits)[valid]
    truth = target[valid]
    intersection = (prob * truth).sum()
    dice = 1 - (2 * intersection + 1) / (prob.sum() + truth.sum() + 1)
    return bce + dice


def chip_iou(model: torch.nn.Module | None, image: np.ndarray, label: np.ndarray, threshold: float, device: torch.device) -> float:
    batch = image[None, ...]
    if model is None:
        probability = threshold_probability(batch, threshold)[0, 0]
    else:
        model.eval()
        tensor = torch.from_numpy(normalize_db(batch)).to(device)
        with torch.no_grad():
            probability = torch.sigmoid(model(tensor))[0, 0].detach().cpu().numpy()
    return iou_score(probability >= 0.5, label)


def macro(scores: list[float]) -> float:
    return float(np.mean(scores)) if scores else 0.0


def event_macro(chips: list[dict], scores: list[float]) -> float:
    by_event: dict[str, list[float]] = {}
    for chip, score in zip(chips, scores, strict=True):
        by_event.setdefault(chip["event"], []).append(score)
    if not by_event:
        return 0.0
    return macro([macro(values) for values in by_event.values()])


def score_chips(model: torch.nn.Module | None, chips: list[dict], device: torch.device) -> list[float]:
    return [chip_iou(model, chip["image"], chip["label"], chip["threshold"], device) for chip in chips]


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    device = torch.device(torch_device())
    if device.type != "cuda":
        raise SystemExit("Este pase pide la GPU. PyTorch no ve CUDA en este entorno.")
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.benchmark = True
    print(f"dispositivo = {device} ({torch.cuda.get_device_name(0)})", flush=True)

    catalog = json.loads(CHIPS.read_text())
    thresholds = event_thresholds()
    chips = []
    features = catalog["features"]
    print(f"cargando {len(features)} chips desde {RAW}…", flush=True)
    for index, feature in enumerate(features, start=1):
        chip_id = feature["properties"]["chipId"]
        event = feature["properties"]["prefix"]
        if event not in thresholds:
            raise RuntimeError(f"{chip_id} no tiene umbral VH.")
        image, label = load_chip(chip_id)
        chips.append(
            {
                "id": chip_id,
                "event": event,
                "image": image,
                "label": label,
                "threshold": thresholds[event],
            }
        )
        if index % 50 == 0 or index == len(features):
            print(f"  {index}/{len(features)}", flush=True)

    by_id = {chip["id"]: chip for chip in chips}
    missing_legacy = [chip_id for chip_id in LEGACY_HELDOUT if chip_id not in by_id]
    if missing_legacy:
        raise RuntimeError(f"Faltan chips del corte anterior: {missing_legacy}.")

    event_holdout = [chip for chip in chips if chip["event"] in HOLDOUT_EVENTS]
    legacy = [by_id[chip_id] for chip_id in LEGACY_HELDOUT]
    blocked = {chip["id"] for chip in event_holdout} | {chip["id"] for chip in legacy}
    train_chips = [chip for chip in chips if chip["id"] not in blocked]
    if not train_chips or not event_holdout:
        raise RuntimeError("El corte de entrenamiento ha quedado vacío.")

    SPLIT_OUT.write_text(
        json.dumps(
            {
                "note": (
                    "Corte por evento. España y Ghana no entran en el entrenamiento. "
                    "Los 11 chips del corte anterior tampoco, para poder comparar el IoU con 0,61."
                ),
                "holdout_events": list(HOLDOUT_EVENTS),
                "legacy_held_out": LEGACY_HELDOUT,
                "event_held_out": [chip["id"] for chip in event_holdout],
                "train": [chip["id"] for chip in train_chips],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(
        f"train={len(train_chips)} eventos_apartados={len(event_holdout)} "
        f"({', '.join(HOLDOUT_EVENTS)}) legacy={len(legacy)}",
        flush=True,
    )

    vh_event_scores = score_chips(None, event_holdout, device)
    vh_event = event_macro(event_holdout, vh_event_scores)
    vh_legacy = macro(score_chips(None, legacy, device))
    print(f"iou umbral VH eventos={vh_event:.4f} legacy={vh_legacy:.4f}", flush=True)

    model = FloodUNet().to(device)
    if not WEIGHTS.exists():
        raise RuntimeError(f"Falta el checkpoint {WEIGHTS}.")
    model.load_state_dict(torch.load(WEIGHTS, map_location=device, weights_only=True))
    old_event_scores = score_chips(model, event_holdout, device)
    old_event = event_macro(event_holdout, old_event_scores)
    old_legacy = macro(score_chips(model, legacy, device))
    print(f"iou checkpoint actual eventos={old_event:.4f} legacy={old_legacy:.4f}", flush=True)
    for event_name in HOLDOUT_EVENTS:
        subset = [chip for chip in event_holdout if chip["event"] == event_name]
        subset_scores = [score for chip, score in zip(event_holdout, old_event_scores, strict=True) if chip["event"] == event_name]
        vh_subset = [score for chip, score in zip(event_holdout, vh_event_scores, strict=True) if chip["event"] == event_name]
        print(
            f"  {event_name}: checkpoint={macro(subset_scores):.4f} umbral={macro(vh_subset):.4f} n={len(subset)}",
            flush=True,
        )

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    best_iou = -1.0
    best_state = None
    stale = 0
    epochs_ran = 0

    for epoch in range(1, EPOCHS + 1):
        epochs_ran = epoch
        model.train()
        random.shuffle(train_chips)
        losses: list[float] = []
        for start in range(0, len(train_chips), BATCH):
            batch = train_chips[start : start + BATCH]
            images = []
            labels = []
            for chip in batch:
                image, label = augment(chip["image"], chip["label"])
                images.append(image)
                labels.append(label)
            stacked = np.stack([normalize_db(image[None])[0] for image in images])
            x = torch.from_numpy(stacked).to(device)
            y = torch.from_numpy(np.stack(labels)).to(device)
            logits = model(x).squeeze(1)
            loss = dice_bce(logits, y)
            if loss is None:
                continue
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        scheduler.step()
        event_scores = score_chips(model, event_holdout, device)
        val_iou = event_macro(event_holdout, event_scores)
        mean_loss = float(np.mean(losses)) if losses else float("nan")
        print(
            f"epoch {epoch}/{EPOCHS} loss={mean_loss:.4f} val_iou={val_iou:.4f} lr={scheduler.get_last_lr()[0]:.6f}",
            flush=True,
        )
        if val_iou > best_iou:
            best_iou = val_iou
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= PATIENCE:
                print(f"parada temprana en la época {epoch}", flush=True)
                break

    if best_state is None:
        raise RuntimeError("El entrenamiento no produjo un checkpoint.")
    model.load_state_dict(best_state)
    new_event_scores = score_chips(model, event_holdout, device)
    new_event = event_macro(event_holdout, new_event_scores)
    new_legacy = macro(score_chips(model, legacy, device))
    per_event = {}
    for event_name in HOLDOUT_EVENTS:
        per_event[event_name] = {
            "n": sum(chip["event"] == event_name for chip in event_holdout),
            "checkpoint": round(
                macro([score for chip, score in zip(event_holdout, old_event_scores, strict=True) if chip["event"] == event_name]),
                4,
            ),
            "fine_tune": round(
                macro([score for chip, score in zip(event_holdout, new_event_scores, strict=True) if chip["event"] == event_name]),
                4,
            ),
            "threshold": round(
                macro([score for chip, score in zip(event_holdout, vh_event_scores, strict=True) if chip["event"] == event_name]),
                4,
            ),
        }
        print(
            f"  {event_name}: fine-tune={per_event[event_name]['fine_tune']:.4f} "
            f"checkpoint={per_event[event_name]['checkpoint']:.4f} umbral={per_event[event_name]['threshold']:.4f}",
            flush=True,
        )
    print(f"fine-tune eventos={new_event:.4f} legacy={new_legacy:.4f}", flush=True)

    beats_legacy = new_legacy > old_legacy
    beats_events = new_event > old_event
    beats_threshold = new_event > vh_event
    replace = beats_legacy and beats_events and beats_threshold
    CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, CANDIDATE)
    if replace:
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        torch.save(best_state, WEIGHTS)
        kept = "el fine-tune de 512"
        live_legacy = new_legacy
    else:
        kept = "el checkpoint de 22 chips"
        live_legacy = old_legacy

    reasons = []
    if not beats_legacy:
        reasons.append(f"en los 11 chips queda en {new_legacy:.3f}, por debajo del checkpoint ({old_legacy:.3f})")
    if not beats_events:
        reasons.append(f"en España y Ghana queda en {new_event:.3f}, por debajo del checkpoint ({old_event:.3f})")
    if not beats_threshold:
        reasons.append(f"en España y Ghana no supera el umbral VH ({vh_event:.3f})")

    card = {
        "model_name": "flood_segmentation_model",
        "model_version": "1",
        "backend": "pytorch_unet",
        "architecture": "U-Net pequeño (16-32-64-96), sin backbone ResNet-18",
        "ran_dali": False,
        "ran_tao": False,
        "ran_tensorrt": False,
        "ran_triton": False,
        "downloaded_hand_labeled": len(chips),
        "train_chips": len(train_chips),
        "held_out_chips": len(legacy),
        "held_out_events": list(HOLDOUT_EVENTS),
        "event_held_out_chips": len(event_holdout),
        "stratified_subset": False,
        "epochs": epochs_ran,
        "epochs_max": EPOCHS,
        "patience": PATIENCE,
        "crop": 512,
        "batch_size": BATCH,
        "loss": "binary cross-entropy + dice",
        "augmentations": "rotaciones de 90 grados y volteos",
        "learning_rate": LR,
        "warm_start": True,
        "train_device": torch.cuda.get_device_name(0),
        "previous_unet_iou": round(old_legacy, 4),
        "previous_reported_iou": PREVIOUS_REPORTED_IOU,
        "retrained_unet_iou": round(new_legacy, 4),
        "threshold_iou": round(vh_legacy, 4),
        "event_previous_iou": round(old_event, 4),
        "event_retrained_iou": round(new_event, 4),
        "event_threshold_iou": round(vh_event, 4),
        "per_event_iou": per_event,
        "unet_iou": round(live_legacy, 4),
        "weights_kept": kept,
        "normalization_db": {"vv": [-25.0, 0.0], "vh": [-35.0, -5.0]},
        "input": "Sentinel-1 VV y VH en dB, forma [1, 2, 512, 512], float32",
        "output": "Probabilidad de agua, forma [1, 1, 512, 512], float32",
        "optional_input": "vh_threshold, float32 [1], umbral del evento en dB. Solo lo usa el backend de umbral.",
        "weights": "services/inference/weights/flood_unet.pt",
        "decision": "",
    }
    if replace:
        card["decision"] = (
            f"Entrenamiento en GPU con {len(train_chips)} chips a 512, pérdida BCE+Dice, "
            f"España y Ghana apartadas ({len(event_holdout)} chips) y los mismos 11 chips de antes. "
            f"IoU del fine-tune en esos 11: {new_legacy:.3f} (checkpoint {old_legacy:.3f}, umbral {vh_legacy:.3f}). "
            f"IoU macro por evento en España y Ghana: {new_event:.3f} "
            f"(checkpoint {old_event:.3f}, umbral {vh_event:.3f}). El servicio carga {kept}."
        )
    else:
        card["decision"] = (
            f"Entrenamiento en GPU con {len(train_chips)} chips a 512 y pérdida BCE+Dice. "
            f"No sustituye al checkpoint de 22 chips: " + "; ".join(reasons) + ". "
            f"IoU del fine-tune en los 11 chips {new_legacy:.3f}; en España y Ghana {new_event:.3f}. "
            f"El servicio sigue cargando {kept}."
        )
    CARD.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    print(card["decision"], flush=True)


if __name__ == "__main__":
    main()
