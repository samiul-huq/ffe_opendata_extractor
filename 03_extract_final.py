#!/usr/bin/env python
"""
Script 3: Final extraction.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import json
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import ijson


SCRIPT1_CONTEXT_FILE = Path("inputs/.run_context_s1.json")
SCRIPT2_CONTEXT_FILE = Path("inputs/.run_context_s2.json")
LIST_PATH_CANDIDATES = ("item", "data.item", "results.item", "items.item", "rows.item")


def load_context(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_crosswalk(csv_path: Path) -> dict[int, str]:
    mapping: dict[int, str] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                rid = int(row["id_region"])
            except Exception:
                continue
            nuts3 = row.get("nuts3", "").strip()
            if nuts3:
                mapping[rid] = nuts3
    return mapping


def detect_list_path(path: Path, candidates: tuple[str, ...] = LIST_PATH_CANDIDATES) -> str | None:
    for cand in candidates:
        with path.open("rb") as f:
            try:
                it = ijson.items(f, cand)
                first = next(it, None)
                if isinstance(first, dict):
                    return cand
            except Exception:
                pass
    return None


def iter_dataset_rows(path: Path, list_path: str):
    with path.open("rb") as f:
        for row in ijson.items(f, list_path):
            yield row


def infer_expected_values_len(year: int, resolution: str | None) -> int:
    total_hours = 8784 if calendar.isleap(year) else 8760
    if not resolution:
        return total_hours

    r = resolution.strip().lower()
    m = re.search(r"(\d+)\s*(hour|hours|hr|h)", r)
    if m:
        step_h = int(m.group(1))
        if step_h > 0:
            return max(1, total_hours // step_h)

    m = re.search(r"(\d+)\s*(min|minute|minutes)", r)
    if m:
        step_min = int(m.group(1))
        if step_min > 0:
            return max(1, (total_hours * 60) // step_min)

    m = re.search(r"(\d+)\s*(day|days|d)", r)
    if m:
        step_d = int(m.group(1))
        days = 366 if calendar.isleap(year) else 365
        if step_d > 0:
            return max(1, days // step_d)

    return total_hours


def hourly_index(year: int) -> list[str]:
    start = datetime(year, 1, 1, 0, 0, 0)
    n = 8784 if calendar.isleap(year) else 8760
    return [(start + timedelta(hours=i)).isoformat(sep=" ") for i in range(n)]


def safe_name(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum() or ch in ("-", "_"))


def json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"{obj.__class__.__name__} is not JSON serializable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Final country NUTS-3 extraction pipeline.")
    parser.add_argument("--id-opendata", type=int, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--country-code", default=None)
    parser.add_argument("--context-file-s1", default=str(SCRIPT1_CONTEXT_FILE), help="Script 1 context")
    parser.add_argument("--context-file-s2", default=str(SCRIPT2_CONTEXT_FILE), help="Script 2 context")
    parser.add_argument("--input-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--dataset-file", default=None)
    parser.add_argument("--crosswalk-csv", default=None)
    parser.add_argument("--jsonl-out", default=None)
    parser.add_argument("--write-hourly-csv", action="store_true", default=True)
    parser.add_argument("--no-hourly-csv", action="store_true")
    parser.add_argument("--hourly-out-dir", default=None)
    parser.add_argument("--internal-id-1", type=int, default=2)
    parser.add_argument("--internal-id-2", type=int, default=72)
    parser.add_argument("--expected-values-len", type=int, default=None)
    args = parser.parse_args()

    if args.no_hourly_csv:
        args.write_hourly_csv = False

    s1_path = Path(args.context_file_s1)
    s2_path = Path(args.context_file_s2)
    s1 = load_context(s1_path)
    s2 = load_context(s2_path)

    id_opendata = args.id_opendata if args.id_opendata is not None else s2.get("id_opendata", s1.get("id_opendata", 103))
    year = args.year if args.year is not None else s2.get("year", s1.get("year", 2019))

    country_code = (args.country_code or s2.get("country_code") or "DE").upper()
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        print(f"ERROR: invalid country code '{country_code}'. Expected 2 letters, e.g. DE.")
        return 1

    input_root = args.input_root or s2.get("input_root") or s1.get("input_root", "inputs")
    output_root = args.output_root or s2.get("output_root") or s1.get("output_root", "outputs")

    input_base = Path(input_root) / f"id_opendata_{id_opendata}"
    output_base = Path(output_root) / f"id_opendata_{id_opendata}"

    default_dataset = input_base / f"id_opendata_{id_opendata}_year_{year}.json"
    fallback_dataset = input_base / f"id_opendata_{id_opendata}.json"
    dataset_path = Path(args.dataset_file) if args.dataset_file else default_dataset
    if not dataset_path.exists() and args.dataset_file is None and fallback_dataset.exists():
        dataset_path = fallback_dataset

    if args.crosswalk_csv:
        crosswalk_path = Path(args.crosswalk_csv)
    elif s2.get("crosswalk_csv"):
        crosswalk_path = Path(s2["crosswalk_csv"])
    else:
        crosswalk_path = output_base / "crosswalk" / f"{country_code}_NUTS3_2021.csv"

    jsonl_out_path = Path(args.jsonl_out) if args.jsonl_out else output_base / "extracted" / f"id_opendata_{id_opendata}_year_{year}_{country_code}_NUTS3.jsonl.gz"
    hourly_out_dir = Path(args.hourly_out_dir) if args.hourly_out_dir else output_base / "hourly" / f"{country_code}_nuts3_internal_id1_{args.internal_id_1}_internal_id2_{args.internal_id_2}_year_{year}"

    if not dataset_path.exists():
        print(f"ERROR: missing dataset file: {dataset_path}")
        return 1
    if not crosswalk_path.exists():
        print(f"ERROR: missing crosswalk file: {crosswalk_path}")
        return 1

    dataset_list_path = detect_list_path(dataset_path)
    if not dataset_list_path:
        print("ERROR: could not detect list path in dataset JSON.")
        return 1

    crosswalk = load_crosswalk(crosswalk_path)
    if not crosswalk:
        print("ERROR: crosswalk mapping is empty.")
        return 1

    resolution = s1.get("timeseries_resolution")
    expected_values_len = args.expected_values_len or infer_expected_values_len(year, resolution)

    print("Starting extraction")
    print(f"- script1 context: {s1_path}")
    print(f"- script2 context: {s2_path}")
    print(f"- id_opendata: {id_opendata}")
    print(f"- country_code: {country_code}")
    print(f"- dataset: {dataset_path}")
    print(f"- dataset list path: {dataset_list_path}")
    print(f"- crosswalk: {crosswalk_path}")
    print(f"- crosswalk rows: {len(crosswalk)}")
    print(f"- year filter: {year}")
    print(f"- timeseries resolution: {resolution}")
    print(f"- expected values length: {expected_values_len}")
    print(f"- jsonl output: {jsonl_out_path}")

    jsonl_out_path.parent.mkdir(parents=True, exist_ok=True)

    writers: dict[str, csv.writer] = {}
    fhs: dict[str, object] = {}
    ts = hourly_index(year) if args.write_hourly_csv else []

    if args.write_hourly_csv:
        hourly_out_dir.mkdir(parents=True, exist_ok=True)
        print(f"- hourly csv dir: {hourly_out_dir}")
        print(f"- hourly filters: internal_id_1={args.internal_id_1}, internal_id_2={args.internal_id_2}")

    scanned = 0
    year_match = 0
    crosswalk_match = 0
    hourly_written = 0
    skipped_shape = 0

    try:
        with gzip.open(jsonl_out_path, "wt", encoding="utf-8") as out_f:
            for rec in iter_dataset_rows(dataset_path, dataset_list_path):
                scanned += 1
                if not isinstance(rec, dict):
                    continue
                if rec.get("year") != year:
                    continue
                year_match += 1

                rid = rec.get("id_region")
                if not isinstance(rid, int) or rid not in crosswalk:
                    continue
                crosswalk_match += 1
                nuts3 = crosswalk[rid]
                rec["nuts3"] = nuts3

                out_f.write(json.dumps(rec, ensure_ascii=False, default=json_default))
                out_f.write("\n")

                if not args.write_hourly_csv:
                    continue
                if rec.get("internal_id_1") != args.internal_id_1:
                    continue
                if rec.get("internal_id_2") != args.internal_id_2:
                    continue

                values = rec.get("values")
                if not isinstance(values, list) or len(values) != expected_values_len:
                    skipped_shape += 1
                    continue

                if nuts3 not in writers:
                    p = hourly_out_dir / f"{safe_name(nuts3)}_{year}.csv"
                    fh = p.open("w", newline="", encoding="utf-8")
                    wr = csv.writer(fh)
                    wr.writerow(["timestamp", "value"])
                    writers[nuts3] = wr
                    fhs[nuts3] = fh

                wr = writers[nuts3]
                for i, val in enumerate(values):
                    wr.writerow([ts[i], val])
                hourly_written += 1
    finally:
        for fh in fhs.values():
            fh.close()

    if args.write_hourly_csv:
        index_path = hourly_out_dir / "INDEX.csv"
        with index_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["nuts3", "file"])
            for nuts3 in sorted(writers.keys()):
                name = f"{safe_name(nuts3)}_{year}.csv"
                w.writerow([nuts3, str(hourly_out_dir / name)])

    print("\nDone")
    print(f"- scanned records: {scanned:,}")
    print(f"- matching year: {year_match:,}")
    print(f"- {country_code} crosswalk matches: {crosswalk_match:,}")
    if args.write_hourly_csv:
        print(f"- hourly series written: {hourly_written:,}")
        print(f"- hourly rows skipped (shape mismatch): {skipped_shape:,}")
    print(f"- output file: {jsonl_out_path}")

    if s2_path.exists():
        s2_path.unlink()
        print(f"- script2 context reset: {s2_path}")
    if s1_path.exists():
        s1_path.unlink()
        print(f"- script1 context reset: {s1_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
