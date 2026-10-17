#!/usr/bin/env python3
"""CPU fine-tune of the small flood U-Net on a stratified Sen1Floods11 subset.

The public hand-labeled set is 446 chips. A full pass on CPU is slow, so this
script trains on data/metadata/train_split.json (every hand-labeled event, the
original 11 chips held out). It warm-starts from the 22-chip checkpoint and
replaces those weights only when held-out macro IoU improves on both that
checkpoint and the VH threshold. This does not run TAO, TensorRT, or Triton.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import tifffile
import torch
import torch.nn.functional as F

from segment import FloodUNet, iou_score, normalize_db, threshold_probability

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
SPLIT = ROOT / "data" / "metadata" / "train_split.json"
FALLBACK_SPLITS = ROOT / "data" / "fixtures" / "splits.json"
WEIGHTS = Path(__file__).resolve().parent / "weights" / "flood_unet.pt"
CARD = Path(__file__).resolve().parent / "model_card.json"

EPOCHS = 8
CROP = 256
BATCH = 4
LR = 3e-4
SEED = 11
PREVIOUS_REPORTED_IOU = 0.6097


def load_chip(chip_id: str) -> tuple[np.ndarray, np.ndarray]:
    image = np.squeeze(tifffile.imread(RAW / f"{chip_id}_S1Hand.tif")).astype(np.float32)
    label = np.squeeze(tifffile.imread(RAW / f"{chip_id}_LabelHand.tif")).astype(np.int16)
    if image.shape[0] != 2:
        image = np.moveaxis(image, -1, 0)
    # A few public chips store NoData as NaN. Left in, they poison BatchNorm.
    image = np.nan_to_num(image, nan=-25.0, posinf=0.0, neginf=-40.0)
    return image, label


def crop_pair(image: np.ndarray, label: np.ndarray, size: int = CROP) -> tuple[np.ndarray, np.ndarray]:
    _, height, width = image.shape
    for _ in range(6):
        y = random.randint(0, height - size)
        x = random.randint(0, width - size)
        lab = label[y : y + size, x : x + size]
        if np.any(lab == 1) and np.mean(lab != -1) > 0.4:
            return image[:, y : y + size, x : x + size], lab
    y = random.randint(0, height - size)
    x = random.randint(0, width - size)
    return image[:, y : y + size, x : x + size], label[y : y + size, x : x + size]


def macro_iou(model: torch.nn.Module | None, chips: list[tuple[np.ndarray, np.ndarray, float]]) -> float:
    scores = []
    for image, label, thresh in chips:
        batch = image[None, ...]
        if model is None:
            prob = threshold_probability(batch, thresh)[0, 0]
        else:
            model.eval()
            normalized = normalize_db(batch)
            tensor = torch.from_numpy(normalized)
            with torch.no_grad():
                prob = torch.sigmoid(model(tensor))[0, 0].cpu().numpy()
        scores.append(iou_score(prob >= 0.5, label))
    return float(np.mean(scores)) if scores else 0.0


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(4)

    source = SPLIT if SPLIT.exists() else FALLBACK_SPLITS
    splits = json.loads(source.read_text())
    thresholds: dict[str, float] = splits["vh_threshold_by_chip"]
    print(f"cargando chips desde {source.name}…", flush=True)
    train_chips = [(cid, *load_chip(cid), thresholds[cid]) for cid in splits["train"]]
    val_chips = [(cid, *load_chip(cid), thresholds[cid]) for cid in splits["held_out"]]
    val_for_iou = [(image, label, thresh) for _, image, label, thresh in val_chips]
    print(f"train={len(train_chips)} held_out={len(val_chips)}", flush=True)

    baseline = macro_iou(None, val_for_iou)
    print(f"iou umbral VH (held-out, macro) = {baseline:.4f}", flush=True)

    model = FloodUNet()
    previous_iou = None
    if WEIGHTS.exists():
        state = torch.load(WEIGHTS, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        previous_iou = macro_iou(model, val_for_iou)
        print(f"iou del checkpoint de 22 chips = {previous_iou:.4f}", flush=True)

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    best_iou = -1.0
    best_state = None

    for epoch in range(1, EPOCHS + 1):
        model.train()
        random.shuffle(train_chips)
        losses = []
        batch_x: list[np.ndarray] = []
        batch_y: list[np.ndarray] = []

        def step() -> None:
            if not batch_x:
                return
            images = np.stack([normalize_db(img[None])[0] for img in batch_x])
            labels = np.stack(batch_y)
            x = torch.from_numpy(images)
            y = torch.from_numpy(labels)
            logits = model(x).squeeze(1)
            valid = y != -1
            if int(valid.sum()) == 0:
                batch_x.clear()
                batch_y.clear()
                return
            target = (y == 1).float()
            loss = F.binary_cross_entropy_with_logits(logits[valid], target[valid])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
            batch_x.clear()
            batch_y.clear()

        for _cid, image, label, _thresh in train_chips:
            cropped, lab = crop_pair(image, label)
            batch_x.append(cropped)
            batch_y.append(lab)
            if len(batch_x) == BATCH:
                step()
        step()
        model.eval()
        val_iou = macro_iou(model, val_for_iou)
        mean_loss = float(np.mean(losses)) if losses else float("nan")
        print(f"epoch {epoch}/{EPOCHS} loss={mean_loss:.4f} val_iou={val_iou:.4f}", flush=True)
        if val_iou > best_iou:
            best_iou = val_iou
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    reference = previous_iou if previous_iou is not None else PREVIOUS_REPORTED_IOU
    replace = best_state is not None and best_iou > baseline and best_iou > reference
    if replace and best_state is not None:
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        torch.save(best_state, WEIGHTS)
        live_iou = best_iou
        kept = "el fine-tune"
    elif WEIGHTS.exists() and previous_iou is not None and previous_iou >= baseline:
        live_iou = previous_iou
        kept = "el checkpoint de 22 chips"
    elif best_state is not None and best_iou > baseline:
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        torch.save(best_state, WEIGHTS)
        live_iou = best_iou
        kept = "el fine-tune"
    else:
        live_iou = best_iou
        kept = "el umbral VH"

    downloaded = int(splits.get("downloaded_hand_labeled", len(train_chips) + len(val_chips)))
    use_unet = kept != "el umbral VH"
    card = {
        "model_name": "flood_segmentation_model",
        "model_version": "1",
        "backend": "pytorch_unet" if use_unet else "vh_threshold",
        "architecture": "U-Net pequeño (16-32-64-96), sin backbone ResNet-18",
        "ran_dali": False,
        "ran_tao": False,
        "ran_tensorrt": False,
        "ran_triton": False,
        "downloaded_hand_labeled": downloaded,
        "train_chips": len(train_chips),
        "held_out_chips": len(val_chips),
        "stratified_subset": True,
        "epochs": EPOCHS,
        "crop": CROP,
        "learning_rate": LR,
        "warm_start": previous_iou is not None,
        "previous_unet_iou": round(reference, 4),
        "retrained_unet_iou": round(best_iou, 4),
        "threshold_iou": round(baseline, 4),
        "unet_iou": round(live_iou, 4),
        "weights_kept": kept,
        "normalization_db": {"vv": [-25.0, 0.0], "vh": [-35.0, -5.0]},
        "input": "Sentinel-1 VV y VH en dB, forma [1, 2, 512, 512], float32",
        "output": "Probabilidad de agua, forma [1, 1, 512, 512], float32",
        "optional_input": "vh_threshold, float32 [1], umbral del evento en dB. Solo lo usa el backend de umbral.",
        "decision": "",
    }
    if use_unet:
        card["weights"] = "services/inference/weights/flood_unet.pt"
        card["decision"] = (
            f"Se descargaron {downloaded} chips etiquetados a mano y se reentrenó un subconjunto "
            f"estratificado de {len(train_chips)} (los 11 eventos, mismos {len(val_chips)} chips apartados). "
            f"IoU del fine-tune {best_iou:.3f}; IoU del modelo de 22 chips {reference:.3f}; "
            f"IoU del umbral VH {baseline:.3f}. El servicio carga {kept}. "
            "No es un motor TensorRT ni un modelo TAO."
        )
    else:
        card["decision"] = (
            f"El fine-tune (IoU {best_iou:.3f}) no supera al umbral VH "
            f"(IoU {baseline:.3f}) ni mejora el checkpoint anterior (IoU {reference:.3f}). "
            "El servicio devuelve la máscara VH < umbral del evento."
        )
    CARD.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    print(card["decision"], flush=True)


if __name__ == "__main__":
    main()
