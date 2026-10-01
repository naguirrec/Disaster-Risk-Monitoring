#!/usr/bin/env python3
"""Build the local Sen1Floods11 catalog and small chip fixtures.

Reads metadata, STAC items, and hand labels already downloaded under a cache
directory (default /tmp/sen1). Writes:

- src/data/events.json
- src/data/chips.json
- data/metadata/Sen1Floods11_Metadata.geojson
- data/metadata/chips.geojson   (v1.1 stand-in for CNN_Chips_FTC.geojson)
- data/fixtures/<chip>.npz
- public/previews/<chip>.png

Raw GeoTIFFs stay in the cache and are copied to data/raw/, which is gitignored.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path("/tmp/sen1")
PIXEL_M = 10.0
PIXEL_KM2 = (PIXEL_M * PIXEL_M) / 1_000_000.0

# location in Sen1Floods11_Metadata.geojson -> chip filename prefix
PREFIX = {
    "Bolivia": "Bolivia",
    "Colombia": None,
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

SPANISH = {
    "Bolivia": ("bolivia", "Bolivia"),
    "Colombia": ("colombia", "Colombia"),
    "Ghana": ("ghana", "Ghana"),
    "India": ("india", "India"),
    "Cambodia": ("camboya", "Camboya"),
    "Nigeria": ("nigeria", "Nigeria"),
    "Pakistan": ("pakistan", "Pakistán"),
    "Paraguay": ("paraguay", "Paraguay"),
    "Somalia": ("somalia", "Somalia"),
    "Spain": ("espana", "España"),
    "Sri-Lanka": ("sri-lanka", "Sri Lanka"),
    "USA": ("estados-unidos", "Estados Unidos"),
}

MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]

# Two public chips per hand-labeled event. The first is held out of training.
SAMPLES = {
    "Bolivia": [("Bolivia_242570", "held_out"), ("Bolivia_294583", "train")],
    "Ghana": [("Ghana_319168", "held_out"), ("Ghana_141910", "train")],
    "India": [("India_1068117", "held_out"), ("India_1050276", "train")],
    "Cambodia": [("Mekong_16233", "held_out"), ("Mekong_293769", "train")],
    "Nigeria": [("Nigeria_598959", "held_out"), ("Nigeria_1095404", "train")],
    "Pakistan": [("Pakistan_1036366", "held_out"), ("Pakistan_1027214", "train")],
    "Paraguay": [("Paraguay_896458", "held_out"), ("Paraguay_1029191", "train")],
    "Somalia": [("Somalia_12849", "held_out"), ("Somalia_970508", "train")],
    "Spain": [("Spain_3285448", "held_out"), ("Spain_8565131", "train")],
    "Sri-Lanka": [("Sri-Lanka_847275", "held_out"), ("Sri-Lanka_92824", "train")],
    "USA": [("USA_366607", "held_out"), ("USA_86502", "train")],
}

# Extra chips used only to train, not shipped as viewer fixtures.
TRAIN_EXTRA = [
    "Bolivia_290290",
    "Ghana_362274",
    "India_804466",
    "Mekong_342411",
    "Nigeria_600295",
    "Pakistan_94095",
    "Paraguay_657443",
    "Somalia_322855",
    "Spain_7370579",
    "Sri-Lanka_14484",
    "USA_217598",
]


def spanish_date(value: str) -> str:
    year, month, day = value.replace("-", "/").split("/")
    return f"{int(day)} de {MONTHS[int(month) - 1]} de {year}"


def orbit_es(value: str) -> str:
    return "Ascendente" if value.upper().startswith("ASC") else "Descendente"


def centroid(geometry: dict) -> list[float]:
    ring = geometry["coordinates"][0]
    xs = [p[0] for p in ring[:-1]]
    ys = [p[1] for p in ring[:-1]]
    return [sum(xs) / len(xs), sum(ys) / len(ys)]


def bounds(geometry: dict) -> list[float]:
    ring = geometry["coordinates"][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def label_stats(arr: np.ndarray) -> dict:
    water = int(np.sum(arr == 1))
    dry = int(np.sum(arr == 0))
    nodata = int(np.sum(arr == -1))
    valid = water + dry
    return {
        "waterPixels": water,
        "dryPixels": dry,
        "nodataPixels": nodata,
        "validPixels": valid,
        "waterFraction": (water / valid) if valid else 0.0,
        "referenceAreaKm2": water * PIXEL_KM2,
    }


# Linear scale stored in the fixture. The VH window covers every event threshold
# in the metadata (about -25 to -19 dB), so a per-event threshold keeps the same
# water / no-water decision except within one quantization step (~0.14 dB).
VV_LO, VV_HI = -30.0, 0.0
VH_LO, VH_HI = -40.0, -5.0


def quantize(band: np.ndarray, lo: float, hi: float) -> np.ndarray:
    clean = np.nan_to_num(band.astype(np.float32), nan=lo, posinf=hi, neginf=lo)
    scaled = (clean - lo) / (hi - lo)
    return np.clip(np.rint(scaled * 255.0), 0, 255).astype(np.uint8)


def sar_png(vh: np.ndarray) -> Image.Image:
    clean = np.nan_to_num(vh.astype(np.float32), nan=np.nanmedian(vh[np.isfinite(vh)]))
    lo, hi = np.percentile(clean, [2, 98])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = -30.0, -5.0
    scaled = np.clip((clean - lo) / (hi - lo), 0, 1)
    gray = np.rint(scaled * 255.0).astype(np.uint8)
    return Image.fromarray(gray, mode="L")


def main() -> None:
    meta_src = CACHE / "Sen1Floods11_Metadata.geojson"
    meta = json.loads(meta_src.read_text())
    meta_dir = ROOT / "data" / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(meta_src, meta_dir / "Sen1Floods11_Metadata.geojson")

    stac_dir = CACHE / "stac"
    label_dir = CACHE / "labels"
    s1_dir = CACHE / "s1"

    by_prefix: dict[str, list[dict]] = defaultdict(list)
    features = []
    chips = []

    for path in sorted(stac_dir.glob("*.json")):
        item = json.loads(path.read_text())
        chip_id = item["id"]
        prefix = chip_id.rsplit("_", 1)[0]
        label = tifffile.imread(label_dir / f"{chip_id}_LabelHand.tif")
        stats = label_stats(label)
        bbox = item["bbox"]
        geometry = item["geometry"]
        props = {
            "chipId": chip_id,
            "prefix": prefix,
            "country": item["properties"].get("country"),
            "datetime": item["properties"].get("datetime"),
            **stats,
        }
        features.append(
            {
                "type": "Feature",
                "id": chip_id,
                "properties": props,
                "bbox": bbox,
                "geometry": geometry,
            }
        )
        by_prefix[prefix].append(
            {
                "chipId": chip_id,
                "bbox": bbox,
                "geometry": geometry,
                **stats,
            }
        )

    sample_ids = {chip_id for pairs in SAMPLES.values() for chip_id, _ in pairs}
    role_of = {chip_id: role for pairs in SAMPLES.values() for chip_id, role in pairs}

    events = []
    for feature in meta["features"]:
        props = feature["properties"]
        location = props["location"]
        slug, nombre = SPANISH[location]
        prefix = PREFIX[location]
        event_chips = by_prefix.get(prefix, []) if prefix else []
        event_chips.sort(key=lambda c: c["chipId"])
        sample = []
        for chip_id, role in SAMPLES.get(location, []):
            match = next(c for c in event_chips if c["chipId"] == chip_id)
            sample.append({"chipId": chip_id, "role": role, **{k: match[k] for k in match if k != "chipId"}})
        events.append(
            {
                "id": int(props["ID"]),
                "slug": slug,
                "location": location,
                "nombre": nombre,
                "iso": props["ISO_CC"],
                "prefix": prefix,
                "s1Date": props["s1_date"].replace("/", "-"),
                "s2Date": props["s2_date"].replace("/", "-"),
                "s1DateEs": spanish_date(props["s1_date"]),
                "s2DateEs": spanish_date(props["s2_date"]),
                "orbit": props["orbit"],
                "orbitEs": orbit_es(props["orbit"]),
                "relativeOrbit": int(props["rel_orbit_num"]),
                "vhThreshold": float(props["VH_thresh"]),
                "trainChipsMeta": int(props["train_chip"]),
                "valChipsMeta": int(props["val_chip"]),
                "coincidentSize": int(props["coincident_size"]),
                "handLabeledCount": len(event_chips),
                "sampleCount": len(sample),
                "centroid": centroid(feature["geometry"]),
                "bounds": bounds(feature["geometry"]),
                "geometry": feature["geometry"],
                "hasHandLabels": len(event_chips) > 0,
            }
        )

    events.sort(key=lambda e: e["nombre"])

    for event in events:
        if not event["prefix"]:
            continue
        for chip in by_prefix[event["prefix"]]:
            chips.append(
                {
                    "chipId": chip["chipId"],
                    "eventSlug": event["slug"],
                    "nombre": event["nombre"],
                    "location": event["location"],
                    "prefix": event["prefix"],
                    "s1DateEs": event["s1DateEs"],
                    "orbitEs": event["orbitEs"],
                    "relativeOrbit": event["relativeOrbit"],
                    "vhThreshold": event["vhThreshold"],
                    "bbox": chip["bbox"],
                    "geometry": chip["geometry"],
                    "waterPixels": chip["waterPixels"],
                    "validPixels": chip["validPixels"],
                    "nodataPixels": chip["nodataPixels"],
                    "waterFraction": chip["waterFraction"],
                    "referenceAreaKm2": chip["referenceAreaKm2"],
                    "hasFixture": chip["chipId"] in sample_ids,
                    "role": role_of.get(chip["chipId"]),
                }
            )

    chips.sort(key=lambda c: (c["nombre"], c["chipId"]))

    src_data = ROOT / "src" / "data"
    src_data.mkdir(parents=True, exist_ok=True)
    (src_data / "events.json").write_text(json.dumps(events, ensure_ascii=False))
    (src_data / "chips.json").write_text(json.dumps(chips, ensure_ascii=False))

    geo = {
        "type": "FeatureCollection",
        "name": "sen1floods11_hand_labeled_chips_v1_1",
        "note": (
            "Huellas de los 446 chips etiquetados a mano, reconstruidas desde el "
            "catálogo STAC v1.1. CNN_Chips_FTC.geojson no está publicado en "
            "gs://sen1floods11/v1.1/ (HTTP 404)."
        ),
        "features": features,
    }
    (meta_dir / "chips.geojson").write_text(json.dumps(geo))

    fixtures = ROOT / "data" / "fixtures"
    previews = ROOT / "public" / "previews"
    raw = ROOT / "data" / "raw"
    fixtures.mkdir(parents=True, exist_ok=True)
    previews.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    manifest = []
    needed = sorted(sample_ids | set(TRAIN_EXTRA))
    for chip_id in needed:
        s1_src = s1_dir / f"{chip_id}_S1Hand.tif"
        label_src = label_dir / f"{chip_id}_LabelHand.tif"
        if not s1_src.exists():
            raise SystemExit(f"Falta el ráster {s1_src}")
        shutil.copyfile(s1_src, raw / s1_src.name)
        shutil.copyfile(label_src, raw / label_src.name)
        if chip_id not in sample_ids:
            continue
        arr = tifffile.imread(s1_src)
        label = tifffile.imread(label_src)
        np.savez_compressed(
            fixtures / f"{chip_id}.npz",
            vv=quantize(arr[0], VV_LO, VV_HI),
            vh=quantize(arr[1], VH_LO, VH_HI),
            label=label.astype(np.int8),
            vv_lo=np.float32(VV_LO),
            vv_hi=np.float32(VV_HI),
            vh_lo=np.float32(VH_LO),
            vh_hi=np.float32(VH_HI),
        )
        sar_png(arr[1]).save(previews / f"{chip_id}.jpg", quality=82, optimize=True)
        manifest.append(
            {
                "chipId": chip_id,
                "role": role_of[chip_id],
                "fixture": f"data/fixtures/{chip_id}.npz",
                "preview": f"/previews/{chip_id}.jpg",
                "quantization": {
                    "vv": [VV_LO, VV_HI],
                    "vh": [VH_LO, VH_HI],
                    "dtype": "uint8",
                },
            }
        )

    (fixtures / "manifest.json").write_text(json.dumps(manifest, indent=2))
    splits = {
        "held_out": [chip_id for pairs in SAMPLES.values() for chip_id, role in pairs if role == "held_out"],
        "train": [chip_id for pairs in SAMPLES.values() for chip_id, role in pairs if role == "train"]
        + TRAIN_EXTRA,
        "vh_threshold_by_chip": {
            chip["chipId"]: next(e["vhThreshold"] for e in events if e["slug"] == chip["eventSlug"])
            for chip in chips
            if chip["hasFixture"] or chip["chipId"] in TRAIN_EXTRA
        },
    }
    # Thresholds for extra training chips are not in `chips` fixtures filter above
    # when the extra id is absent from the sample flag. Fill from prefix.
    prefix_thresh = {e["prefix"]: e["vhThreshold"] for e in events if e["prefix"]}
    for chip_id in TRAIN_EXTRA:
        prefix = chip_id.rsplit("_", 1)[0]
        splits["vh_threshold_by_chip"][chip_id] = prefix_thresh[prefix]
    (fixtures / "splits.json").write_text(json.dumps(splits, indent=2))
    print(f"events={len(events)} chips={len(chips)} fixtures={len(manifest)}")


if __name__ == "__main__":
    main()
