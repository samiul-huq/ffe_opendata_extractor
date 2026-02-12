# FfE OpenData Country NUTS-3 Extraction Pipeline

This repository provides a 3-script workflow to:

1. Download static FfE OpenData files
2. Build a country-specific NUTS-3 crosswalk
3. Extract final records and per-region hourly CSV outputs

## Note: This code has only been tested with the data available at https://opendata.ffe.de/dataset/load-curves-of-the-industry-sector-including-feedstock-europe-nuts-3/ with the data for DE and DK for the year 2019.

## Files

- `01_download_assets.py`
- `02_build_de_crosswalk.py`
- `03_extract_final.py`
- `requirements.txt`
- `.gitignore`
- `LICENSE`

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run in order:

```powershell
python 01_download_assets.py
python 02_build_de_crosswalk.py
python 03_extract_final.py
```

## Standard Runtime Structure

These folders are created automatically when scripts run:

- `inputs/id_opendata_<id>/...`
- `outputs/id_opendata_<id>/crosswalk/...`
- `outputs/id_opendata_<id>/extracted/...`
- `outputs/id_opendata_<id>/hourly/...`

`inputs/` and `outputs/` are git-ignored.

## Script Details

### 1) `01_download_assets.py`

- Prompts for `id_opendata` and `year`
- Downloads:
  - metadata JSON
  - dataset JSON
  - `v_region_simple` helper file
- Inspects region helper metadata/data and lists available 2-letter country codes
- Prompts you to select the target country code
- Writes:
  - `inputs/id_opendata_<id>/manifest.json`
  - `inputs/.run_context.json` (temporary context for scripts 2 and 3)

### 2) `02_build_de_crosswalk.py`

- Reads region helper file
- Uses selected country code from run context (or `--country-code` override)
- Extracts country NUTS-3 rows (`<CC>***`)
- Performs encoding cleanup for common mojibake artifacts
- Writes:
  - `<CC>_NUTS3_2021.csv`
  - `<CC>_NUTS3_2021.json`
  - `<CC>_NUTS3_2021_excel.csv`

### 3) `03_extract_final.py`

- Reads dataset + country crosswalk
- Filters by year and selected-country region mapping
- Writes compressed JSONL output
- Writes per-region hourly CSV output automatically (default enabled)
- Removes `inputs/.run_context.json` after successful completion

Use `--no-hourly-csv` if you only want JSONL output.

## Limitations

1. Static URL dependency  
   Download logic assumes FfE static blob naming remains stable.

2. Input schema dependency  
   Parser expects array-like JSON dataset structure; source schema changes may break parsing.

3. Numeric precision conversion  
   Decimal values are converted to float during JSON serialization.

4. Hourly-series expectation  
   Hourly CSV export expects `values` length 8760; malformed rows are skipped.

5. Country-code derivation  
   Country options are derived from region helper `name_short` prefixes.

6. No resume/checkpoint downloads  
   Large file downloads are retried by rerunning script 1.

7. No automated tests/CI yet  
   Validation is performed by runtime checks and output diagnostics.

## License

This code is licensed under the MIT License (`LICENSE`).

Important: dataset licensing is separate from code licensing.  
Always follow the original FfE/OpenData dataset terms and attribution requirements.
