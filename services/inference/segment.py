"""Portable flood segmentation.

The HTTP contract lives in server.py and matches Triton:
model name flood_segmentation_model, image in, mask out.

This module is not TAO, TensorRT, or Triton. It either runs a small PyTorch
U-Net trained in this repo or the documented Sentinel-1 VH threshold from
Sen1Floods11_Metadata.geojson. model_card.json says which one is active.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover - the service image always installs torch
    torch = None
    nn = None

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "model_card.json"
WEIGHTS_PATH = ROOT / "weights" / "flood_unet.pt"

# Display / network normalization of Sentinel-1 dB.
NORM_VV = (-25.0, 0.0)
NORM_VH = (-35.0, -5.0)
DEFAULT_VH_THRESHOLD = -21.69


def torch_device() -> str:
    """cuda cuando este proceso ve una GPU NVIDIA; si no, cpu."""
    if torch is not None and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def dequantize(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return values.astype(np.float32) / 255.0 * (hi - lo) + lo


def normalize_db(image_db: np.ndarray) -> np.ndarray:
    """image_db: [N, 2, H, W] VV/VH in dB -> [0, 1]."""
    vv_lo, vv_hi = NORM_VV
    vh_lo, vh_hi = NORM_VH
    clean = np.nan_to_num(image_db, nan=-25.0, posinf=0.0, neginf=-40.0)
    out = np.empty_like(clean, dtype=np.float32)
    out[:, 0] = np.clip((clean[:, 0] - vv_lo) / (vv_hi - vv_lo), 0, 1)
    out[:, 1] = np.clip((clean[:, 1] - vh_lo) / (vh_hi - vh_lo), 0, 1)
    return out


def threshold_probability(image_db: np.ndarray, vh_threshold: float) -> np.ndarray:
    """Water where VH (dB) is below the event threshold. Shape [N, 1, H, W]."""
    water = image_db[:, 1] < vh_threshold
    return water.astype(np.float32)[:, None, :, :]


def iou_score(prediction: np.ndarray, label: np.ndarray) -> float:
    """prediction bool/0-1, label with -1 nodata, 0 dry, 1 water."""
    valid = label != -1
    pred = prediction.astype(bool) & valid
    truth = (label == 1) & valid
    inter = np.logical_and(pred, truth).sum()
    union = np.logical_or(pred, truth).sum()
    if union == 0:
        return 1.0
    return float(inter) / float(union)


if nn is not None:

    class DoubleConv(nn.Module):
        def __init__(self, cin: int, cout: int) -> None:
            super().__init__()
            self.block = nn.Sequential(
                nn.Conv2d(cin, cout, 3, padding=1, bias=False),
                nn.BatchNorm2d(cout),
                nn.ReLU(inplace=True),
                nn.Conv2d(cout, cout, 3, padding=1, bias=False),
                nn.BatchNorm2d(cout),
                nn.ReLU(inplace=True),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.block(x)

    class FloodUNet(nn.Module):
        """Small U-Net. Not ResNet-18 and not a TAO export."""

        def __init__(self) -> None:
            super().__init__()
            self.e1 = DoubleConv(2, 16)
            self.e2 = DoubleConv(16, 32)
            self.e3 = DoubleConv(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = DoubleConv(64, 96)
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)
            self.d3 = DoubleConv(96 + 64, 64)
            self.d2 = DoubleConv(64 + 32, 32)
            self.d1 = DoubleConv(32 + 16, 16)
            self.head = nn.Conv2d(16, 1, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            e1 = self.e1(x)
            e2 = self.e2(self.pool(e1))
            e3 = self.e3(self.pool(e2))
            b = self.bottleneck(self.pool(e3))
            d3 = self.d3(torch.cat([self.up(b), e3], dim=1))
            d2 = self.d2(torch.cat([self.up(d3), e2], dim=1))
            d1 = self.d1(torch.cat([self.up(d2), e1], dim=1))
            return self.head(d1)

else:  # pragma: no cover
    FloodUNet = None  # type: ignore


class Segmenter:
    def __init__(self) -> None:
        self.card = {
            "model_name": "flood_segmentation_model",
            "model_version": "1",
            "backend": "vh_threshold",
            "notes": "model_card.json todavía no existe; se usa el umbral VH.",
        }
        self.model = None
        self.device = torch_device()
        if CARD_PATH.exists():
            self.card = json.loads(CARD_PATH.read_text())
        backend = self.card.get("backend", "vh_threshold")
        if backend == "pytorch_unet":
            if torch is None or FloodUNet is None:
                raise RuntimeError("El model card pide el U-Net, pero PyTorch no está instalado.")
            if not WEIGHTS_PATH.exists():
                raise RuntimeError(f"Faltan los pesos {WEIGHTS_PATH}.")
            self.model = FloodUNet().to(self.device)
            state = torch.load(WEIGHTS_PATH, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            self.model.eval()

    @property
    def backend(self) -> str:
        return str(self.card.get("backend", "vh_threshold"))

    def predict(self, image_db: np.ndarray, vh_threshold: float | None) -> np.ndarray:
        """image_db float32 [1, 2, H, W] in dB. Returns float32 [1, 1, H, W] in [0, 1]."""
        if image_db.ndim != 4 or image_db.shape[1] != 2:
            raise ValueError("La entrada debe tener forma [N, 2, H, W].")
        if self.backend == "pytorch_unet" and self.model is not None and torch is not None:
            normalized = normalize_db(image_db)
            tensor = torch.from_numpy(normalized).to(self.device)
            with torch.no_grad():
                logits = self.model(tensor)
                prob = torch.sigmoid(logits)
            return prob.detach().cpu().numpy().astype(np.float32)
        thresh = DEFAULT_VH_THRESHOLD if vh_threshold is None else float(vh_threshold)
        return threshold_probability(image_db, thresh)
