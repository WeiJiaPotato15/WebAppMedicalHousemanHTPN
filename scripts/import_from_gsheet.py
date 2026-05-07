"""One-shot importer: pull a Google Sheets weekly tab (CSV export) into the roster table.

The current Hospital Tengku Permaisuri Norashikin sheet is publicly viewable, so we read it as CSV via:

    https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<TAB_ID>

The expected layout is the existing roster: column 1 = officer name, columns 2..8 =
each day Mon..Sun with shift codes in cells. This script accepts a flexible header row
and tries a few common shapes; if it cannot detect, it asks you to specify column ranges.

Usage:
    python scripts/import_from_gsheet.py \
        --csv-url 'https://...export?format=csv&gid=...' \
        --week-start 2026-05-04 \
        --actor leader@example.com
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db import get_store  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv-url", required=True, help="CSV export URL of the weekly tab")
    p.add_argument("--week-start", required=True, help="Monday of the target week, YYYY-MM-DD")
    p.add_argument("--actor", required=True, help="Email to attribute the import as")
    p.add_argument("--name-col", default=0, type=int, help="Column index for officer name (default 0)")
    p.add_argument("--first-day-col", default=1, type=int,
                   help="Column index of Monday's shift (default 1)")
    p.add_argument("--limit-rows", default=200, type=int, help="Safety cap on rows imported")
    args = p.parse_args()

    monday = date.fromisoformat(args.week_start)
    if monday.weekday() != 0:
        print(f"WARNING: {monday} is a {monday.strftime('%A')}, not Monday. Continuing anyway.")

    df = pd.read_csv(args.csv_url, header=None, dtype=str).fillna("")
    print(f"Read {len(df)} rows × {df.shape[1]} cols from CSV.")

    store = get_store()
    # Build email lookup once.
    officers = store.list_officers()
    if not officers:
        print("ERROR: no officers in the database. Add officers via the Officers page first.",
              file=sys.stderr)
        return 1
    by_name_lower = {o.name.strip().lower(): o.ic_number for o in officers}

    days = [monday + timedelta(days=i) for i in range(7)]
    imported = 0
    skipped_unknown = []
    for i, row in df.head(args.limit_rows).iterrows():
        raw_name = str(row.iloc[args.name_col]).strip()
        if not raw_name or raw_name.lower() in {"name", "ho", "houseman", "house officer"}:
            continue
        ic_number = by_name_lower.get(raw_name.lower())
        if not ic_number:
            skipped_unknown.append(raw_name)
            continue
        for d_idx, d in enumerate(days):
            col = args.first_day_col + d_idx
            if col >= df.shape[1]:
                break
            code = str(row.iloc[col]).strip()
            if not code:
                continue
            store.set_assignment(ic_number=ic_number, on_date=d, shift_code=code, actor_email=args.actor)
            imported += 1

    print(f"Imported {imported} assignments.")
    if skipped_unknown:
        print(f"Skipped {len(skipped_unknown)} rows with unknown names:")
        for n in skipped_unknown[:20]:
            print(f"  - {n}")
        if len(skipped_unknown) > 20:
            print(f"  … and {len(skipped_unknown) - 20} more")
        print("Add these officers via the Officers page (or correct the names) and re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
