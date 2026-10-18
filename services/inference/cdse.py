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


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _odata_day(value: str, end: bool) -> str:
    if not isinstance(value, str) or not _DAY.match(value):
        raise CdseError("La fecha tiene que ir como AAAA-MM-DD.")
    clock = "23:59:59.000Z" if end else "00:00:00.000Z"
    return f"{value}T{clock}"


def _point(lon: float, lat: float) -> str:
    lon = float(lon)
    lat = float(lat)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise CdseError("El punto queda fuera de lon/lat.")
    return f"POINT({lon} {lat})"


def search_scenes(
    bounds: list[float] | None = None,
    days: int = 120,
    start: str | None = None,
    end: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    top: int = 8,
) -> list[dict[str, str]]:
    if not credentials_configured():
        raise CdseError("Faltan CDSE_USERNAME y CDSE_PASSWORD.")
    if lon is not None and lat is not None:
        area = _point(lon, lat)
    elif bounds is not None:
        area = _bounds_polygon(bounds)
    else:
        raise CdseError("Falta el punto o la huella.")
    if start and end:
        date_filter = (
            f"ContentDate/Start gt {_odata_day(start, False)} and "
            f"ContentDate/Start lt {_odata_day(end, True)}"
        )
    else:
        opened = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
        date_filter = f"ContentDate/Start gt {opened}"
    limit = min(max(int(top), 1), 12)
    filt = (
        "Collection/Name eq 'SENTINEL-1' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
        "att/OData.CSC.StringAttribute/Value eq 'GRD') and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'operationalMode' and "
        "att/OData.CSC.StringAttribute/Value eq 'IW') and "
        f"{date_filter} and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{area}')"
    )
    query = urllib.parse.urlencode(
        {
            "$filter": filt,
            "$orderby": "ContentDate/Start desc",
            "$top": str(limit),
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


def _convex_hull(points: np.ndarray) -> np.ndarray:
    ordered = points[np.lexsort((points[:, 1], points[:, 0]))]
    unique = [ordered[0]]
    for point in ordered[1:]:
        if not np.array_equal(point, unique[-1]):
            unique.append(point)

    def chain(seq: list[np.ndarray]) -> list[np.ndarray]:
        hull: list[np.ndarray] = []
        for point in seq:
            while len(hull) >= 2:
                a, b = hull[-2], hull[-1]
                cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
                if cross > 0:
                    break
                hull.pop()
            hull.append(point)
        return hull

    lower = chain(unique)
    upper = chain(unique[::-1])
    return np.array(lower[:-1] + upper[:-1], dtype=np.float64)


def _inside_polygon(polygon: np.ndarray, lon: float, lat: float) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        yi, yj = polygon[i, 1], polygon[j, 1]
        xi, xj = polygon[i, 0], polygon[j, 0]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def _pixel_from_gcps(gcps, lon: float, lat: float, height: int, width: int) -> tuple[int, int]:
    points = np.array([[point.x, point.y, point.col, point.row] for point in gcps], dtype=np.float64)
    hull = _convex_hull(points[:, :2])
    if not _inside_polygon(hull, lon, lat):
        raise CdseError("El centro de la huella cae fuera de esta escena.")
    distance = (points[:, 0] - lon) ** 2 + (points[:, 1] - lat) ** 2
    nearest = np.argsort(distance)[:6]
    design = np.column_stack([points[nearest, 0], points[nearest, 1], np.ones(nearest.size)])
    col_coef, *_ = np.linalg.lstsq(design, points[nearest, 2], rcond=None)
    row_coef, *_ = np.linalg.lstsq(design, points[nearest, 3], rcond=None)
    sample = np.array([lon, lat, 1.0])
    col = float(col_coef @ sample)
    row = float(row_coef @ sample)
    if not (0 <= row < height and 0 <= col < width):
        raise CdseError("El centro de la huella cae fuera de esta escena.")
    return int(round(row)), int(round(col))


def _lonlat_from_pixel(gcps, col: float, row: float) -> tuple[float, float]:
    points = np.array([[point.col, point.row, point.x, point.y] for point in gcps], dtype=np.float64)
    distance = (points[:, 0] - col) ** 2 + (points[:, 1] - row) ** 2
    nearest = np.argsort(distance)[:6]
    design = np.column_stack([points[nearest, 0], points[nearest, 1], np.ones(nearest.size)])
    lon_coef, *_ = np.linalg.lstsq(design, points[nearest, 2], rcond=None)
    lat_coef, *_ = np.linalg.lstsq(design, points[nearest, 3], rcond=None)
    sample = np.array([col, row, 1.0], dtype=np.float64)
    return float(lon_coef @ sample), float(lat_coef @ sample)


def _chip_corners(path: Path, col0: int, row0: int, size: int) -> list[list[float]]:
    import rasterio

    with rasterio.open(path) as src:
        gcps, _crs = src.gcps
        if not gcps:
            raise CdseError("La medición no trae puntos de control para colocarla en el mapa.")
        corners = (
            (col0, row0),
            (col0 + size, row0),
            (col0 + size, row0 + size),
            (col0, row0 + size),
        )
        return [[lon, lat] for lon, lat in (_lonlat_from_pixel(gcps, col, row) for col, row in corners)]


def _read_window(path: Path, lon: float, lat: float, size: int = CHIP) -> tuple[np.ndarray, np.ndarray]:
    try:
        import rasterio
        from rasterio.transform import rowcol
        from rasterio.windows import Window
    except ImportError as exc:
        raise CdseError("Falta rasterio para recortar el GeoTIFF de la escena.") from exc
    with rasterio.open(path) as src:
        if src.height < size or src.width < size:
            raise CdseError("La medición es más pequeña que el recorte pedido.")
        gcps, _crs = src.gcps
        if gcps:
            row, col = _pixel_from_gcps(gcps, lon, lat, src.height, src.width)
        else:
            row, col = rowcol(src.transform, lon, lat)
            row, col = int(row), int(col)
            if not (0 <= row < src.height and 0 <= col < src.width):
                raise CdseError("El centro de la huella cae fuera de esta escena.")
        row0 = int(np.clip(row - size // 2, 0, src.height - size))
        col0 = int(np.clip(col - size // 2, 0, src.width - size))
        data = src.read(1, window=Window(col0, row0, size, size)).astype(np.float32)
    return data, np.array([row0, col0], dtype=np.int32)


def _to_db(dn: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    sigma0 = (dn * dn) / np.maximum(sigma * sigma, 1e-6)
    db = 10.0 * np.log10(np.maximum(sigma0, 1e-8))
    return np.nan_to_num(db, nan=-40.0, posinf=0.0, neginf=-40.0).astype(np.float32)


def _stretch(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip((values - lo) / max(hi - lo, 1e-3), 0, 1)


def _false_color(vv_db: np.ndarray, vh_db: np.ndarray) -> np.ndarray:
    # Fixed decibel windows, so two dates stay comparable. Red is VV, green is VH,
    # blue is the VV/VH ratio in dB. Smooth water stays dark.
    red = _stretch(vv_db, -20.0, 0.0)
    green = _stretch(vh_db, -28.0, -8.0)
    blue = _stretch(vv_db - vh_db, 2.0, 16.0)
    return np.stack([red, green, blue], axis=-1)


def _png_data(image: np.ndarray, mode: str) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(image, mode=mode).save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _preview(vh_db: np.ndarray, water: np.ndarray, vv_db: np.ndarray | None = None) -> str:
    if vv_db is None:
        finite = vh_db[np.isfinite(vh_db)]
        lo, hi = np.percentile(finite, [5, 95]) if finite.size else (-30, -5)
        gray = np.clip((vh_db - lo) / max(hi - lo, 1e-3), 0, 1)
        rgb = np.stack([gray, gray, gray], axis=-1)
    else:
        rgb = _false_color(vv_db, vh_db)
    rgb = rgb.copy()
    rgb[water] = rgb[water] * 0.35 + np.array([0.11, 0.55, 0.62])
    return _png_data((rgb * 255).astype(np.uint8), "RGB")


def _sar_png(vv_db: np.ndarray, vh_db: np.ndarray) -> str:
    return _png_data((_false_color(vv_db, vh_db) * 255).astype(np.uint8), "RGB")


def _mask_png(water: np.ndarray) -> str:
    rgba = np.zeros((*water.shape, 4), dtype=np.uint8)
    rgba[water] = (28, 148, 168, 188)
    return _png_data(rgba, "RGBA")


def segment_scene(
    product_id: str,
    lon: float,
    lat: float,
    vh_threshold: float,
    segmenter,
    tiles: int = 1,
) -> dict:
    tiles = 2 if int(tiles) == 2 else 1
    span = CHIP * tiles
    folder = _download(product_id)
    vv_path = next(folder.glob("*-vv-*.tif*"))
    vh_path = next(folder.glob("*-vh-*.tif*"))
    # Calibration XML names look like calibration-s1a-iw-grd-vv-....xml
    vv_cal = next(path for path in folder.glob("calibration-*-vv-*.xml"))
    vh_cal = next(path for path in folder.glob("calibration-*-vh-*.xml"))
    try:
        vv_dn, origin = _read_window(vv_path, lon, lat, span)
        vh_dn, _origin = _read_window(vh_path, lon, lat, span)
    except CdseError:
        if tiles == 1:
            raise
        tiles = 1
        span = CHIP
        vv_dn, origin = _read_window(vv_path, lon, lat, span)
        vh_dn, _origin = _read_window(vh_path, lon, lat, span)
    row0, col0 = int(origin[0]), int(origin[1])
    vv_db = _to_db(vv_dn, _calibration_grid(vv_cal, row0, col0, span, span))
    vh_db = _to_db(vh_dn, _calibration_grid(vh_cal, row0, col0, span, span))
    valid = (vv_dn > 0) & (vh_dn > 0)
    probability = np.zeros((span, span), dtype=np.float32)
    for tile_row in range(tiles):
        for tile_col in range(tiles):
            row = tile_row * CHIP
            col = tile_col * CHIP
            image = np.stack(
                [
                    vv_db[row : row + CHIP, col : col + CHIP],
                    vh_db[row : row + CHIP, col : col + CHIP],
                ]
            )[None, ...]
            probability[row : row + CHIP, col : col + CHIP] = segmenter.predict(
                image, float(vh_threshold)
            )[0, 0]
    water = (probability >= 0.5) & valid
    threshold_water = (vh_db < float(vh_threshold)) & valid
    area = float(water.sum() * PIXEL_KM2)
    threshold_area = float(threshold_water.sum() * PIXEL_KM2)
    return {
        "product_id": product_id,
        "area_km2": round(area, 3),
        "threshold_area_km2": round(threshold_area, 3),
        "valid_pixels": int(valid.sum()),
        "water_pixels": int(water.sum()),
        "tiles": tiles,
        "span_px": span,
        "span_km": round(span * 10 / 1000, 2),
        "corners": _chip_corners(vh_path, col0, row0, span),
        "backend": segmenter.backend,
        "device": segmenter.device,
        "preview_png": _preview(vh_db, water, vv_db),
        "sar_png": _sar_png(vv_db, vh_db),
        "mask_png": _mask_png(water),
    }
