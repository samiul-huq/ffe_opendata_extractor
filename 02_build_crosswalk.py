#!/usr/bin/env python
"""
Script 2: Build country NUTS-3 crosswalk from region helper JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import ijson


SCRIPT1_CONTEXT_FILE = Path("inputs/.run_context_s1.json")
SCRIPT2_CONTEXT_FILE = Path("inputs/.run_context_s2.json")
LIST_PATH_CANDIDATES = ("data.item", "item", "results.item", "items.item", "rows.item")


def ask(text: str, default: str | None = None, example: str | None = None) -> str:
    label = f"{text}"
    if example is not None:
        label += f" [e.g. {example}]"
    label += ": "
    value = input(label).strip()
    if not value and default is not None:
        return default
    return value


def fix_mojibake(text: str) -> str:
    if not isinstance(text, str):
        return text
    if "Ã" in text or "â" in text or "�" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except Exception:
            return text
    return text


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


def iter_rows(path: Path, list_path: str):
    with path.open("rb") as f:
        for row in ijson.items(f, list_path):
            yield row


def discover_country_codes(region_path: Path, list_path: str) -> list[str]:
    codes = set()
    for row in iter_rows(region_path, list_path):
        if not isinstance(row, dict):
            continue
        short_code = row.get("name_short")
        if not isinstance(short_code, str):
            continue
        short_code = short_code.strip().upper()
        if len(short_code) < 2:
            continue
        cc = short_code[:2]
        if cc.isalpha():
            codes.add(cc)
    return sorted(codes)


def ask_country_code(options: list[str], preset: str | None) -> str:
    if preset:
        p = preset.upper()
        if options and p in options:
            return p
        if not options and re.fullmatch(r"[A-Z]{2}", p):
            return p

    if options:
        print("\nAvailable country codes:")
        print(", ".join(options))
        default = "DE" if "DE" in options else options[0]
        while True:
            chosen = ask("Country code to process", default=default, example=default).upper()
            if chosen in options:
                return chosen
            print("ERROR: choose one of the listed country codes.")

    return ask("Country code to process", default="DE", example="DE").upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build selected-country NUTS-3 crosswalk CSV/JSON (+ Excel CSV with BOM).")
    parser.add_argument("--id-opendata", type=int, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--country-code", default=None)
    parser.add_argument("--context-file-in", default=str(SCRIPT1_CONTEXT_FILE), help="Script 1 context file")
    parser.add_argument("--context-file-out", default=str(SCRIPT2_CONTEXT_FILE), help="Script 2 context file")
    parser.add_argument("--region-file", default=None)
    parser.add_argument("--input-root", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    s1 = load_context(Path(args.context_file_in))
    id_opendata = args.id_opendata if args.id_opendata is not None else s1.get("id_opendata", 103)
    year = args.year if args.year is not None else s1.get("year", 2019)
    input_root = args.input_root or s1.get("input_root", "inputs")
    output_root = args.output_root or s1.get("output_root", "outputs")

    region_path = Path(args.region_file) if args.region_file else Path(input_root) / f"id_opendata_{id_opendata}" / "v_region_simple.json"
    out_dir = Path(args.out_dir) if args.out_dir else Path(output_root) / f"id_opendata_{id_opendata}" / "crosswalk"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not region_path.exists():
        print(f"ERROR: missing file: {region_path}")
        return 1

    list_path = detect_list_path(region_path)
    if not list_path:
        print("ERROR: could not detect list path in region JSON.")
        return 1

    options = discover_country_codes(region_path, list_path)
    country_code = ask_country_code(options, args.country_code)
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        print(f"ERROR: invalid country code '{country_code}'. Expected 2 letters, e.g. DE.")
        return 1

    country_pattern = re.compile(rf"^{country_code}[A-Z0-9]{{3}}$")

    print("Using standard structure")
    print(f"- script1 context: {args.context_file_in}")
    print(f"- script2 context: {args.context_file-out if False else args.context_file_out}")
    print(f"- id_opendata: {id_opendata}")
    print(f"- year: {year}")
    print(f"- country_code: {country_code}")
    print(f"- region list path: {list_path}")
    print(f"- input region file: {region_path}")
    print(f"- output folder: {out_dir}")

    rows = []
    seen = set()
    skipped_other_country = 0

    for row in iter_rows(region_path, list_path):
        if not isinstance(row, dict):
            continue
        code = row.get("name_short")
        if not isinstance(code, str):
            continue
        code = code.strip().upper()
        if not country_pattern.match(code):
            skipped_other_country += 1
            continue

        rid = row.get("id_region")
        rtype = row.get("id_region_type")
        valid_from = row.get("valid_from")
        region_name = row.get("region")
        if isinstance(region_name, str):
            region_name = fix_mojibake(region_name)

        key = (code, rid, rtype, valid_from)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "nuts3": code,
            "region": region_name,
            "id_region": rid,
            "id_region_type": rtype,
            "valid_from": valid_from,
        })

    rows.sort(key=lambda x: x["nuts3"])

    out_csv = out_dir / f"{country_code}_NUTS3_2021.csv"
    out_json = out_dir / f"{country_code}_NUTS3_2021.json"
    out_csv_excel = out_dir / f"{country_code}_NUTS3_2021_excel.csv"

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["nuts3", "region", "id_region", "id_region_type", "valid_from"])
        writer.writeheader()
        writer.writerows(rows)

    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    out_csv_excel.write_text(out_csv.read_text(encoding="utf-8"), encoding="utf-8-sig")

    unique_nuts3 = len({r["nuts3"] for r in rows})
    unique_id_region = len({r["id_region"] for r in rows})
    format_ok = all(country_pattern.match(r["nuts3"]) for r in rows)

    print("\nValidation")
    print(f"- rows: {len(rows)}")
    print(f"- unique nuts3: {unique_nuts3}")
    print(f"- unique id_region: {unique_id_region}")
    print(f"- format valid: {format_ok}")
    print(f"- skipped non-{country_code} rows: {skipped_other_country}")

    if args.expected_count is not None and len(rows) != args.expected_count:
        msg = f"expected {args.expected_count}, got {len(rows)}."
        if args.strict:
            print(f"ERROR: {msg}")
            return 2
        print(f"WARNING: {msg}")

    s2 = {
        "id_opendata": id_opendata,
        "year": year,
        "country_code": country_code,
        "input_root": input_root,
        "output_root": output_root,
        "region_path": str(region_path),
        "region_list_path": list_path,
        "crosswalk_csv": str(out_csv),
    }
    out_ctx = Path(args.context_file_out)
    out_ctx.parent.mkdir(parents=True, exist_ok=True)
    out_ctx.write_text(json.dumps(s2, indent=2), encoding="utf-8")

    print("\nOutputs")
    print(f"- {out_csv}")
    print(f"- {out_json}")
    print(f"- {out_csv_excel}")
    print(f"- script2 context: {out_ctx}")
    print("\nNext: run script 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
