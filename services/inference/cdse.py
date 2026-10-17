"""Copernicus Data Space client for one Sentinel-1 GRD IW scene.

Reads CDSE_USERNAME and CDSE_PASSWORD from the environment, then from .env
and .env.local if those names are still empty. Tokens and passwords are never
logged. Search uses the public client (cdse-public), the identity host and the
catalogue OData API. A downloaded scene is chipped to 512×512 around the event
centroid and calibrated from GRD digital numbers to sigma0 in dB.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "copernicus"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"
CLIENT_ID = "cdse-public"
PRODUCT_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
CHIP = 512
PIXEL_KM2 = 0.0001


class CdseError(RuntimeError):
    pass


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def credentials() -> tuple[str, str] | None:
    username = os.environ.get("CDSE_USERNAME", "").strip()
    password = os.environ.get("CDSE_PASSWORD", "").strip()
    if not username or not password:
        file_values: dict[str, str] = {}
        for name in (".env", ".env.local"):
            file_values.update(_parse_env_file(ROOT / name))
        username = username or file_values.get("CDSE_USERNAME", "").strip()
        password = password or file_values.get("CDSE_PASSWORD", "").strip()
    if username and password:
        return username, password
    return None


def credentials_configured() -> bool:
    return credentials() is not None


def _token() -> str:
    pair = credentials()
    if pair is None:
        raise CdseError("Faltan CDSE_USERNAME y CDSE_PASSWORD.")
    username, password = pair
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": username,
            "password": password,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise CdseError(f"Copernicus rechazó el inicio de sesión ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise CdseError("No se pudo contactar identity.dataspace.copernicus.eu.") from exc
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise CdseError("Copernicus no devolvió un token.")
    return token


class _KeepAuth(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        host = urllib.parse.urlparse(newurl).hostname or ""
        if host.endswith("dataspace.copernicus.eu"):
            auth = req.get_header("Authorization")
            if auth:
                redirected.add_unredirected_header("Authorization", auth)
        return redirected


def _open(url: str, token: str, timeout: int):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(_KeepAuth)
    return opener.open(request, timeout=timeout)


def _bounds_polygon(bounds: list[float]) -> str:
    if len(bounds) != 4:
        raise CdseError("La huella necesita minLon, minLat, maxLon y maxLat.")
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in bounds)
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise CdseError("La huella queda fuera de lon/lat.")
    if max_lon - min_lon > 30 or max_lat - min_lat > 30:
        raise CdseError("La huella es demasiado grande para una búsqueda.")
    ring = (
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
        (min_lon, min_lat),
    )
    coords = ", ".join(f"{lon} {lat}" for lon, lat in ring)
    return f"POLYGON(({coords}))"


def search_scenes(bounds: list[float], days: int = 120) -> list[dict[str, str]]:
    if not credentials_configured():
        raise CdseError("Faltan CDSE_USERNAME y CDSE_PASSWORD.")
    polygon = _bounds_polygon(bounds)
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
    filt = (
        "Collection/Name eq 'SENTINEL-1' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
        "att/OData.CSC.StringAttribute/Value eq 'GRD') and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'operationalMode' and "
        "att/OData.CSC.StringAttribute/Value eq 'IW') and "
        f"ContentDate/Start gt {start} and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon}')"
    )
    query = urllib.parse.urlencode(
        {
            "$filter": filt,
            "$orderby": "ContentDate/Start desc",
            "$top": "5",
            "$select": "Id,Name,ContentDate",
        },
        safe="$'()",
    )
    token = _token()
    try:
        with _open(f"{CATALOGUE_URL}?{query}", token, timeout=45) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:180]
        raise CdseError(f"El catálogo OData respondió {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise CdseError("No se pudo contactar catalogue.dataspace.copernicus.eu.") from exc
    scenes = []
    for item in payload.get("value", []):
        product_id = str(item.get("Id", ""))
        if not PRODUCT_ID.match(product_id):
            continue
        content = item.get("ContentDate") or {}
        scenes.append(
            {
                "id": product_id,
                "name": str(item.get("Name", product_id)),
                "start": str(content.get("Start", "")),
                "end": str(content.get("End", "")),
            }
        )
    return scenes


def _member(names: list[str], polarization: str, kind: str) -> str:
    pol = f"-{polarization.lower()}-"
    matches = [
        name
        for name in names
        if kind in name
        and pol in name.lower()
        and not name.endswith("/")
    ]
    if not matches:
        raise CdseError(f"La escena no trae {kind} {polarization.upper()}.")
    return matches[0]


def _download(product_id: str) -> Path:
    if not PRODUCT_ID.match(product_id):
        raise CdseError("El identificador de escena no es un UUID.")
    target = CACHE / product_id
    marker = target / "ready.json"
    if marker.is_file():
        return target
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "scene.zip"
    token = _token()
    url = DOWNLOAD_URL.format(product_id=product_id)
    try:
        with _open(url, token, timeout=120) as response, archive.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except urllib.error.HTTPError as exc:
        archive.unlink(missing_ok=True)
        raise CdseError(f"La descarga de la escena falló ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        archive.unlink(missing_ok=True)
        raise CdseError("No se pudo descargar la escena desde zipper.dataspace.copernicus.eu.") from exc
    if archive.stat().st_size < 1024:
        archive.unlink(missing_ok=True)
        raise CdseError("La descarga llegó vacía.")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        wanted = [
            _member(names, "vv", "measurement"),
            _member(names, "vh", "measurement"),
            _member(names, "vv", "annotation/calibration/calibration-"),
            _member(names, "vh", "annotation/calibration/calibration-"),
        ]
        for name in wanted:
            destination = target / Path(name).name
            with bundle.open(name) as source, destination.open("wb") as handle:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    archive.unlink(missing_ok=True)
    marker.write_text(json.dumps({"id": product_id}), encoding="utf-8")
    return target


def _calibration_grid(xml_path: Path, row0: int, col0: int, height: int, width: int) -> np.ndarray:
    root = ET.parse(xml_path).getroot()
    vectors: list[tuple[int, np.ndarray, np.ndarray]] = []
    for node in root.findall(".//calibrationVector"):
        line_text = node.findtext("line")
        pixel_text = node.findtext("pixel")
        sigma_text = node.findtext("sigmaNought")
        if line_text is None or pixel_text is None or sigma_text is None:
            continue
        vectors.append(
            (
                int(line_text),
                np.fromstring(pixel_text, sep=" ", dtype=np.float64),
                np.fromstring(sigma_text, sep=" ", dtype=np.float64),
            )
        )
    if len(vectors) < 2:
        raise CdseError(f"Calibración ilegible en {xml_path.name}.")
    vectors.sort(key=lambda item: item[0])
    lines = np.array([item[0] for item in vectors], dtype=np.int32)
    grid = np.empty((height, width), dtype=np.float32)
    columns = np.arange(col0, col0 + width)
    for index, line in enumerate(range(row0, row0 + height)):
        cursor = int(np.searchsorted(lines, line))
        cursor = min(max(cursor, 1), len(lines) - 1)
        left, right = cursor - 1, cursor
        span = int(lines[right] - lines[left])
        weight = 0.0 if span == 0 else float(line - int(lines[left])) / span
        low = np.interp(columns, vectors[left][1], vectors[left][2])
        high = np.interp(columns, vectors[right][1], vectors[right][2])
        grid[index] = (1.0 - weight) * low + weight * high
    return grid


def _read_window(path: Path, lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    try:
        import rasterio
        from rasterio.transform import rowcol
        from rasterio.windows import Window
    except ImportError as exc:
        raise CdseError("Falta rasterio para recortar el GeoTIFF de la escena.") from exc
    with rasterio.open(path) as src:
        row, col = rowcol(src.transform, lon, lat)
        row = int(row)
        col = int(col)
        if src.height < CHIP or src.width < CHIP:
            raise CdseError("La medición es más pequeña que un chip de 512×512.")
        row0 = int(np.clip(row - CHIP // 2, 0, src.height - CHIP))
        col0 = int(np.clip(col - CHIP // 2, 0, src.width - CHIP))
        data = src.read(1, window=Window(col0, row0, CHIP, CHIP)).astype(np.float32)
    return data, np.array([row0, col0], dtype=np.int32)


def _to_db(dn: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    sigma0 = (dn * dn) / np.maximum(sigma * sigma, 1e-6)
    db = 10.0 * np.log10(np.maximum(sigma0, 1e-8))
    return np.nan_to_num(db, nan=-40.0, posinf=0.0, neginf=-40.0).astype(np.float32)


def _preview(vh_db: np.ndarray, water: np.ndarray) -> str:
    from PIL import Image

    finite = vh_db[np.isfinite(vh_db)]
    lo, hi = np.percentile(finite, [5, 95]) if finite.size else (-30, -5)
    gray = np.clip((vh_db - lo) / max(hi - lo, 1e-3), 0, 1)
    rgb = np.stack([gray, gray, gray], axis=-1)
    rgb[water] = rgb[water] * 0.35 + np.array([0.11, 0.55, 0.62])
    image = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def segment_scene(product_id: str, lon: float, lat: float, vh_threshold: float, segmenter) -> dict:
    folder = _download(product_id)
    vv_path = next(folder.glob("*-vv-*.tif*"))
    vh_path = next(folder.glob("*-vh-*.tif*"))
    # Calibration XML names look like calibration-s1a-iw-grd-vv-....xml
    vv_cal = next(path for path in folder.glob("calibration-*-vv-*.xml"))
    vh_cal = next(path for path in folder.glob("calibration-*-vh-*.xml"))
    vv_dn, origin = _read_window(vv_path, lon, lat)
    vh_dn, _origin = _read_window(vh_path, lon, lat)
    row0, col0 = int(origin[0]), int(origin[1])
    vv_db = _to_db(vv_dn, _calibration_grid(vv_cal, row0, col0, CHIP, CHIP))
    vh_db = _to_db(vh_dn, _calibration_grid(vh_cal, row0, col0, CHIP, CHIP))
    valid = (vv_dn > 0) & (vh_dn > 0)
    image = np.stack([vv_db, vh_db])[None, ...]
    probability = segmenter.predict(image, float(vh_threshold))[0, 0]
    water = (probability >= 0.5) & valid
    area = float(water.sum() * PIXEL_KM2)
    return {
        "product_id": product_id,
        "area_km2": round(area, 3),
        "valid_pixels": int(valid.sum()),
        "water_pixels": int(water.sum()),
        "backend": segmenter.backend,
        "preview_png": _preview(vh_db, water),
    }
