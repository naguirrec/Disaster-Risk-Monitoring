#!/usr/bin/env python3
"""Short CPU training of a small U-Net on the local Sen1Floods11 sample.

Held-out chips are the first sample of each hand-labeled event. The VH
threshold published in Sen1Floods11_Metadata.geojson is the baseline. The
U-Net is kept only when its macro IoU on the held-out chips is higher.
This does not run TAO, TensorRT, or Triton.
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
SPLITS = ROOT / "data" / "fixtures" / "splits.json"
WEIGHTS = Path(__file__).resolve().parent / "weights" / "flood_unet.pt"
CARD = Path(__file__).resolve().parent / "model_card.json"

EPOCHS = 16
CROP = 256
BATCH = 4
LR = 1e-3
SEED = 11


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

    splits = json.loads(SPLITS.read_text())
    thresholds: dict[str, float] = splits["vh_threshold_by_chip"]
    print("cargando chips…", flush=True)
    train_chips = [(cid, *load_chip(cid), thresholds[cid]) for cid in splits["train"]]
    val_chips = [(cid, *load_chip(cid), thresholds[cid]) for cid in splits["held_out"]]
    val_for_iou = [(image, label, thresh) for _, image, label, thresh in val_chips]

    baseline = macro_iou(None, val_for_iou)
    print(f"iou umbral VH (held-out, macro) = {baseline:.4f}", flush=True)

    model = FloodUNet()
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
            for _crop_index in range(2):
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

    use_unet = best_state is not None and best_iou > baseline
    card = {
        "model_name": "flood_segmentation_model",
        "model_version": "1",
        "backend": "pytorch_unet" if use_unet else "vh_threshold",
        "architecture": "U-Net pequeño (16-32-64-96), sin backbone ResNet-18",
        "ran_dali": False,
        "ran_tao": False,
        "ran_tensorrt": False,
        "ran_triton": False,
        "train_chips": len(train_chips),
        "held_out_chips": len(val_chips),
        "epochs": EPOCHS,
        "crop": CROP,
        "threshold_iou": round(baseline, 4),
        "unet_iou": round(best_iou, 4),
        "normalization_db": {"vv": [-25.0, 0.0], "vh": [-35.0, -5.0]},
        "input": "Sentinel-1 VV y VH en dB, forma [1, 2, 512, 512], float32",
        "output": "Probabilidad de agua, forma [1, 1, 512, 512], float32",
        "optional_input": "vh_threshold, float32 [1], umbral del evento en dB. Solo lo usa el backend de umbral.",
        "decision": "",
    }
    if use_unet and best_state is not None:
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        torch.save(best_state, WEIGHTS)
        card["weights"] = "services/inference/weights/flood_unet.pt"
        card["decision"] = (
            f"El U-Net (IoU {best_iou:.3f}) supera al umbral VH (IoU {baseline:.3f}) "
            "en los 11 chips apartados. El servicio portable carga esos pesos. "
            "No es un motor TensorRT ni un modelo TAO."
        )
    else:
        card["decision"] = (
            f"El U-Net (IoU {best_iou:.3f}) no supera al umbral VH de la metadata "
            f"(IoU {baseline:.3f}) en los chips apartados. El servicio devuelve la máscara "
            "VH < umbral del evento. El entrenamiento sí se ejecutó en CPU con PyTorch."
        )
    CARD.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    print(card["decision"], flush=True)


if __name__ == "__main__":
    main()
