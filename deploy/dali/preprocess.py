#!/usr/bin/env python3
"""Preproceso del curso, en dos capas.

La capa que corre sin GPU es la normalización que ya usa el servicio portable.
La capa DALI (decode y resize en GPU) solo se importa si nvidia.dali está
instalado, que es lo que trae la imagen nvcr.io/nvidia/dali del perfil nvidia.
"""

from __future__ import annotations

import sys

import numpy as np

VV_RANGE = (-25.0, 0.0)
VH_RANGE = (-35.0, -5.0)


def normalize_s1(vv: np.ndarray, vh: np.ndarray) -> np.ndarray:
    """Devuelve VV, VH en [0, 1] a partir de decibelios. Misma escala que el U-Net portable."""
    image = np.stack([vv, vh]).astype(np.float32)
    image = np.nan_to_num(image, nan=-25.0, posinf=0.0, neginf=-40.0)
    out = np.empty_like(image)
    out[0] = np.clip((image[0] - VV_RANGE[0]) / (VV_RANGE[1] - VV_RANGE[0]), 0, 1)
    out[1] = np.clip((image[1] - VH_RANGE[0]) / (VH_RANGE[1] - VH_RANGE[0]), 0, 1)
    return out


def gpu_pipeline():
    try:
        from nvidia.dali import pipeline_def
        import nvidia.dali.fn as fn
    except ImportError:
        print(
            "nvidia.dali no está instalado. Este script documenta el preproceso del curso; "
            "en CPU usa normalize_s1. Con GPU, levanta el perfil nvidia de docker compose.",
            file=sys.stderr,
        )
        return None

    @pipeline_def
    def flood_preprocess():
        # Los chips del curso llegan como ficheros de imagen. DALI decodifica,
        # fuerza 512×512 y deja el tensor listo para el U-Net.
        images = fn.readers.file(file_root="/data/raw", random_shuffle=False)
        decoded = fn.decoders.image(images, device="mixed")
        resized = fn.resize(decoded, resize_x=512, resize_y=512)
        return fn.crop_mirror_normalize(
            resized,
            dtype="float",
            output_layout="CHW",
            mean=[0.0, 0.0],
            std=[1.0, 1.0],
        )

    return flood_preprocess(batch_size=1, num_threads=2, device_id=0)


if __name__ == "__main__":
    pipe = gpu_pipeline()
    if pipe is None:
        raise SystemExit(0)
    pipe.build()
    print("Pipeline DALI construido. No se procesa el dataset completo en este arranque.")
