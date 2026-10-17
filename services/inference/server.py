"""Triton-style HTTP endpoint for flood_segmentation_model.

Implements the binary inference extension used by Triton:
Inference-Header-Content-Length plus raw little-endian float32 tensors.

This process is a portable stand-in. It does not load a TensorRT plan and it
does not speak to a Triton server. See model_card.json for the live backend.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cdse import CdseError, credentials_configured, search_scenes, segment_scene
from segment import DEFAULT_VH_THRESHOLD, Segmenter

MODEL = "flood_segmentation_model"
app = FastAPI(title="Inferencia portable de inundación", version="1")
segmenter = Segmenter()


def model_metadata() -> dict[str, Any]:
    platform = "pytorch_libtorch" if segmenter.backend == "pytorch_unet" else "vh_threshold"
    return {
        "name": MODEL,
        "versions": ["1"],
        "platform": platform,
        "backend": segmenter.backend,
        "inputs": [
            {"name": "input", "datatype": "FP32", "shape": [2, 512, 512]},
            {
                "name": "vh_threshold",
                "datatype": "FP32",
                "shape": [1],
                "optional": True,
            },
        ],
        "outputs": [{"name": "output", "datatype": "FP32", "shape": [1, 512, 512]}],
    }


@app.get("/v2/health/live")
@app.get("/v2/health/ready")
def health() -> Response:
    return Response(status_code=200)


@app.get("/v2/models/flood_segmentation_model")
def model_ready() -> dict[str, Any]:
    return model_metadata()


def _parse(raw: bytes, header_len: str | None) -> tuple[dict[str, Any], list[np.ndarray]]:
    if header_len:
        n = int(header_len)
        header = json.loads(raw[:n])
        offset = n
        arrays: list[np.ndarray] = []
        for item in header["inputs"]:
            size = int(item["parameters"]["binary_data_size"])
            chunk = raw[offset : offset + size]
            offset += size
            if len(chunk) != size:
                raise ValueError("El cuerpo binario está incompleto.")
            array = np.frombuffer(chunk, dtype=np.float32).reshape(item["shape"]).copy()
            arrays.append(array)
        return header, arrays
    header = json.loads(raw)
    arrays = []
    for item in header["inputs"]:
        arrays.append(np.asarray(item["data"], dtype=np.float32).reshape(item["shape"]))
    return header, arrays


@app.post("/v2/models/flood_segmentation_model/infer")
async def infer(request: Request) -> Response:
    raw = await request.body()
    try:
        header, arrays = _parse(raw, request.headers.get("inference-header-content-length"))
        inputs = {item["name"]: array for item, array in zip(header["inputs"], arrays, strict=True)}
        if "input" not in inputs:
            raise ValueError("Falta la entrada 'input'.")
        image = inputs["input"]
        if image.shape != (1, 2, 512, 512):
            raise ValueError(f"Forma de entrada {list(image.shape)}; se espera [1, 2, 512, 512].")
        vh_threshold = None
        if "vh_threshold" in inputs:
            vh_threshold = float(inputs["vh_threshold"].reshape(-1)[0])
        prob = segmenter.predict(image, vh_threshold)
        if prob.shape != (1, 1, 512, 512):
            raise RuntimeError(f"Salida inesperada {prob.shape}")
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        body = json.dumps({"error": str(exc)}).encode()
        return Response(content=body, status_code=400, media_type="application/json")

    out = np.ascontiguousarray(prob, dtype=np.float32)
    payload = out.tobytes()
    response_header = {
        "model_name": MODEL,
        "model_version": "1",
        "parameters": {
            "backend": segmenter.backend,
            "vh_threshold": vh_threshold if vh_threshold is not None else DEFAULT_VH_THRESHOLD,
            "ran_triton": False,
        },
        "outputs": [
            {
                "name": "output",
                "shape": [1, 1, 512, 512],
                "datatype": "FP32",
                "parameters": {"binary_data_size": len(payload)},
            }
        ],
    }
    header_bytes = json.dumps(response_header).encode()
    return Response(
        content=header_bytes + payload,
        media_type="application/octet-stream",
        headers={"Inference-Header-Content-Length": str(len(header_bytes))},
    )


@app.get("/cdse/status")
def cdse_status() -> dict[str, object]:
    configured = credentials_configured()
    return {
        "configured": configured,
        "inference": True,
        "message": (
            ""
            if configured
            else "Define CDSE_USERNAME y CDSE_PASSWORD en el entorno o en .env.local y reinicia este servicio."
        ),
    }


@app.post("/cdse/search")
def cdse_search(payload: dict = Body(...)) -> JSONResponse:
    if not credentials_configured():
        return JSONResponse(cdse_status(), status_code=409)
    bounds = payload.get("bounds")
    if not isinstance(bounds, list):
        return JSONResponse({"error": "Falta la huella del evento."}, status_code=400)
    try:
        scenes = search_scenes([float(value) for value in bounds])
    except (CdseError, TypeError, ValueError) as exc:
        return JSONResponse({"configured": True, "error": str(exc)}, status_code=502)
    return JSONResponse({"configured": True, "scenes": scenes})


@app.post("/cdse/segment")
def cdse_segment(payload: dict = Body(...)) -> JSONResponse:
    if not credentials_configured():
        return JSONResponse(cdse_status(), status_code=409)
    try:
        product_id = str(payload["product_id"])
        lon = float(payload["lon"])
        lat = float(payload["lat"])
        vh_threshold = float(payload.get("vh_threshold", DEFAULT_VH_THRESHOLD))
        result = segment_scene(product_id, lon, lat, vh_threshold, segmenter)
    except KeyError:
        return JSONResponse({"error": "Faltan product_id, lon o lat."}, status_code=400)
    except CdseError as exc:
        return JSONResponse({"configured": True, "error": str(exc)}, status_code=502)
    return JSONResponse(result)
