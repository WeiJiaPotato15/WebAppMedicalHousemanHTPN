"""Seed the hkj_shifts table with the 37 codes from the Hospital Kajang Grouping sheet.

Idempotent: re-running upserts the same rows. Safe to use as a "reset to defaults"
button — it does not delete codes you've added; it only writes the seed set.

Usage (locally, with .env populated):
    python scripts/seed_shifts.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `lib` importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.constants import SEED_SHIFTS  # noqa: E402
from lib.db import get_store  # noqa: E402
from lib.models import Shift  # noqa: E402


def main() -> int:
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        print("WARNING: no AWS creds detected — this will seed the in-memory store and exit.")
    store = get_store()
    n = 0
    for s in SEED_SHIFTS:
        store.upsert_shift(Shift(**s))
        n += 1
    print(f"Seeded {n} shift codes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
