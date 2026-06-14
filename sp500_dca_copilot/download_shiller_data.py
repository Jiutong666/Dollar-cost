"""
Download Robert Shiller's S&P 500 historical data (1871-present) from Yale.
Converts the .xls file to a clean CSV for use by the DCA Co-pilot.

Usage:
    python -m sp500_dca_copilot.download_shiller_data
    python -m sp500_dca_copilot.download_shiller_data --output data/my_copy.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import requests

from .config import SHILLER_CSV_PATH

logger = logging.getLogger(__name__)

# Robert Shiller's data URL (stable for decades)
SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"

# Column names for the output CSV
OUTPUT_COLUMNS = [
    "Date",           # Fractional year (e.g. 1871.04)
    "SP500_Price",    # Nominal S&P 500 Composite price (monthly average)
    "Dividend",       # Nominal dividend
    "Earnings",       # Nominal earnings
    "CPI",            # Consumer Price Index
    "Long_Rate",      # Long-term interest rate (GS10)
    "Real_Price",     # Real (inflation-adjusted) S&P 500 price
    "Real_Dividend",  # Real dividend
    "Real_Earnings",  # Real earnings
    "CAPE",           # Cyclically Adjusted PE Ratio (Shiller PE)
]


def download_shiller_xls(target_path: Path) -> None:
    """Download the Shiller .xls file from Yale."""
    logger.info(f"Downloading from {SHILLER_URL}...")
    resp = requests.get(SHILLER_URL, timeout=60)
    resp.raise_for_status()
    target_path.write_bytes(resp.content)
    logger.info(f"Downloaded {len(resp.content)} bytes to {target_path}")


def parse_shiller_xls(xls_path: Path) -> list[dict]:
    """
    Parse the Shiller .xls file using xlrd directly (bypasses Pandas
    which blocks xlrd < 2.0 for .xls files).

    The Shiller spreadsheet has a complex layout:
    - Rows 1-7: Header/metadata
    - Row 8: Column headers (2 sets: left for nominal, right for real)
    - Rows 9+: Monthly data

    Returns list of dicts with cleaned monthly data.
    """
    import xlrd

    wb = xlrd.open_workbook(str(xls_path))

    # The file has two sheets: "Disclaimer" (index 0) and "Data" (index 1)
    if wb.nsheets > 1:
        sh = wb.sheet_by_index(1)
    else:
        sh = wb.sheet_by_index(0)

    logger.info(f"Parsing sheet '{sh.name}': {sh.nrows} rows × {sh.ncols} cols")

    # Actual Shiller spreadsheet layout (sheet "Data"):
    # A(0):  Date (fractional year, e.g. 1871.01)
    # B(1):  S&P Comp. Price (nominal)
    # C(2):  Dividend (nominal)
    # D(3):  Earnings (nominal)
    # E(4):  CPI
    # F(5):  Date Fraction (duplicate)
    # G(6):  Long Interest Rate GS10
    # H(7):  Real Price (inflation-adjusted)
    # I(8):  Real Dividend
    # J(9):  Real Total Return Price
    # K(10): Real Earnings
    # L(11): Real TR Scaled Earnings
    # M(12): CAPE (P/E10 or CAPE) — "NA" before 1881
    # N(13): (empty separator)
    # O(14): TR CAPE
    #
    # Data starts at row 8 (0-indexed), after 7 rows of headers

    def _val(col: int) -> float | None:
        """Read a cell value, returning None for empty/invalid/NA cells."""
        v = sh.cell_value(r, col)
        if v == "" or v is None:
            return None
        if isinstance(v, str) and v.upper().strip() == "NA":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    records = []
    data_start = 8  # 0-indexed row where monthly data begins

    for r in range(data_start, sh.nrows):
        try:
            date_val = sh.cell_value(r, 0)
        except IndexError:
            continue

        # Skip header/empty rows — date should be a number like 1871.01
        if not isinstance(date_val, (int, float)) or date_val == 0:
            continue
        if date_val < 1870 or date_val > 2100:  # Sanity check
            continue

        record = {
            "Date": round(date_val, 2),
            "SP500_Price": _val(1),
            "Dividend": _val(2),
            "Earnings": _val(3),
            "CPI": _val(4),
            "Long_Rate": _val(6),
            "Real_Price": _val(7),
            "Real_Dividend": _val(8),
            "Real_Earnings": _val(10),
            "CAPE": _val(12),
        }

        # Skip rows that are entirely empty in the price column
        if record["SP500_Price"] is None:
            continue

        records.append(record)

    logger.info(f"Parsed {len(records)} monthly records")
    return records


def save_csv(records: list[dict], output_path: Path) -> None:
    """Save the parsed records to a CSV file."""
    import csv

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    logger.info(f"Saved {len(records)} records to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Robert Shiller's S&P 500 historical data"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=SHILLER_CSV_PATH,
        help=f"Output CSV path (default: {SHILLER_CSV_PATH})",
    )
    parser.add_argument(
        "--keep-xls",
        action="store_true",
        help="Keep the downloaded .xls file (default: delete after conversion)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Download to a temp file
    xls_path = args.output.parent / "ie_data.xls"

    try:
        download_shiller_xls(xls_path)
        records = parse_shiller_xls(xls_path)
        if not records:
            logger.error("No records parsed — the Shiller spreadsheet format may have changed.")
            logger.error("Please check http://www.econ.yale.edu/~shiller/data/ie_data.xls manually.")
            sys.exit(1)
        save_csv(records, args.output)
    finally:
        if not args.keep_xls and xls_path.exists():
            xls_path.unlink()
            logger.info(f"Cleaned up {xls_path}")

    # Print summary
    latest = records[-1]
    print()
    print("══╡ Shiller 数据下载完成 ╞" + "═" * 40)
    print(f"  记录数: {len(records)}")
    print(f"  日期范围: {records[0]['Date']} ~ {latest['Date']}")
    print(f"  最新 S&P 500: {latest['SP500_Price']}")
    print(f"  最新 CAPE: {latest['CAPE']}")
    print(f"  保存至: {args.output}")
    print("═" * 56)


if __name__ == "__main__":
    main()
