#!/usr/bin/env python
"""
Script 1: Interactive downloader for FfE OpenData static assets.

What it downloads:
1) Dataset metadata JSON
2) Dataset JSON (optionally year-specific)
3) Region helper file (for script 2)
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


STATIC_ROOT = "https://ffeopendatastorage.blob.core.windows.net/opendata"
DEFAULT_REGION_TYPE = 79
DEFAULT_REGION_URL = f"https://api.opendata.ffe.de/v_region_simple?id_region_type={DEFAULT_REGION_TYPE}"
SCRIPT1_CONTEXT_FILE = Path("inputs/.run_context_s1.json")


def ask(text: str, default: str | None = None, example: str | None = None) -> str:
    label = f"{text}"
    if example is not None:
        label += f" [e.g. {example}]"
    label += ": "
    value = input(label).strip()
    if not value and default is not None:
        return default
    return value


def to_int_or_none(value: str) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_urls(id_opendata: int, year: int | None) -> tuple[str, str]:
    base = f"{STATIC_ROOT}/id_opendata_{id_opendata}"
    metadata_url = f"{base}/id_opendata_{id_opendata}_metadata.json"
    if year is None:
        dataset_url = f"{base}/id_opendata_{id_opendata}.json"
    else:
        dataset_url = f"{base}/id_opendata_{id_opendata}_year_{year}.json"
    return metadata_url, dataset_url


def download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading: {url}")
    try:
        with urllib.request.urlopen(url) as resp, out_path.open("wb") as f:
            total = resp.headers.get("Content-Length")
            total_int = int(total) if total and total.isdigit() else None
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_int:
                    pct = (downloaded / total_int) * 100
                    print(f"  {downloaded:,}/{total_int:,} bytes ({pct:.1f}%)", end="\r")
        if total_int:
            print(" " * 80, end="\r")
        print(f"Saved: {out_path}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} for URL: {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error for URL {url}: {e}") from e


def extract_region_type(meta: dict) -> int:
    ffe = meta.get("ffe_metadata", {}) if isinstance(meta, dict) else {}
    rt = ffe.get("id_region_type")
    if isinstance(rt, list) and rt and isinstance(rt[0], int):
        return rt[0]
    if isinstance(rt, int):
        return rt
    return DEFAULT_REGION_TYPE


def extract_timeseries_resolution(meta: dict) -> str | None:
    try:
        return meta.get("oep_metadata", {}).get("temporal", {}).get("timeseries", {}).get("resolution")
    except Exception:
        return None


def derive_region_url(meta: dict) -> tuple[str, int]:
    region_type = extract_region_type(meta)
    try:
        geom = meta.get("ffe_metadata", {}).get("geometries_simple", [])
        if isinstance(geom, list) and geom and isinstance(geom[0], str):
            return geom[0], region_type
    except Exception:
        pass
    return f"https://api.opendata.ffe.de/v_region_simple?id_region_type={region_type}", region_type


def main() -> int:
    print("FfE OpenData static downloader")
    print("-" * 32)

    id_str = ask("Dataset id_opendata", default="103", example="103")
    try:
        id_opendata = int(id_str)
    except ValueError:
        print("ERROR: id_opendata must be an integer.")
        return 1

    year_raw = ask("Year (blank = full dataset)", default="2019", example="2019")
    year = to_int_or_none(year_raw)
    if year_raw != "" and year is None:
        print("ERROR: year must be an integer or blank.")
        return 1

    out_root = Path("inputs") / f"id_opendata_{id_opendata}"

    metadata_url, dataset_url = build_urls(id_opendata, year)
    metadata_name = f"id_opendata_{id_opendata}_metadata.json"
    dataset_name = f"id_opendata_{id_opendata}.json" if year is None else f"id_opendata_{id_opendata}_year_{year}.json"

    metadata_path = out_root / metadata_name
    dataset_path = out_root / dataset_name
    region_path = out_root / "v_region_simple.json"

    existing_files = [p for p in (metadata_path, dataset_path, region_path) if p.exists()]
    overwrite = False
    if existing_files:
        print("\nExisting files detected:")
        for p in existing_files:
            print(f"- {p}")
        overwrite = ask("Overwrite existing files? (y/n)", default="n", example="n").lower() == "y"

    for target in (metadata_path, dataset_path, region_path):
        if target.exists() and not overwrite:
            print(f"ERROR: {target} exists. No files were overwritten. Please proceed with next script.")
            return 1

    print("\nStep 1/3: metadata")
    download_file(metadata_url, metadata_path)

    print("\nStep 2/3: dataset")
    download_file(dataset_url, dataset_path)

    meta = {}
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    region_url, region_type = derive_region_url(meta)
    ts_resolution = extract_timeseries_resolution(meta)

    print("\nStep 3/3: region helper file for script 2")
    print(f"Using region URL: {region_url}")
    download_file(region_url, region_path)

    manifest = {
        "id_opendata": id_opendata,
        "year": year,
        "region_type": region_type,
        "timeseries_resolution": ts_resolution,
        "metadata_path": str(metadata_path),
        "dataset_path": str(dataset_path),
        "region_path": str(region_path),
        "metadata_url": metadata_url,
        "dataset_url": dataset_url,
        "region_url": region_url,
    }
    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    script1_context = {
        "id_opendata": id_opendata,
        "year": year,
        "region_type": region_type,
        "timeseries_resolution": ts_resolution,
        "input_root": "inputs",
        "output_root": "outputs",
        "manifest_path": str(manifest_path),
        "metadata_path": str(metadata_path),
        "dataset_path": str(dataset_path),
        "region_path": str(region_path),
    }
    SCRIPT1_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT1_CONTEXT_FILE.write_text(json.dumps(script1_context, indent=2), encoding="utf-8")

    print("\nDone.")
    print(f"Files downloaded here: {out_root}")
    print(f"Manifest: {manifest_path}")
    print(f"Detected region_type: {region_type}")
    print(f"Detected timeseries resolution: {ts_resolution}")
    print(f"Script 1 context file: {SCRIPT1_CONTEXT_FILE}")
    print("Next: run script 2 for country selection and crosswalk build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
