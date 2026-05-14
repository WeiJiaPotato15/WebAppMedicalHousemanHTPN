"""Shared constants: week math, color palette, seed shift data, policy thresholds."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

# Allowed ward groups for Officer.ward_group. Drives the dropdown on the
# Officers page; existing officers with values outside this list still load
# (Pydantic doesn't enforce membership), but the UI only offers these.
WARD_GROUPS: list[str] = ["W1", "W2", "W3", "W6"]

# Categories that must have ≥1 HO every day. Zero counts in these rows of the
# Edit Roster's "Staff per category per day" table are highlighted red.
CRITICAL_COVERAGE_CATEGORIES: set[str] = {
    "W1", "W2", "W3", "W6", "OC", "PERI", "MOPD", "PENDING ED",
}

# Categories that allow zero coverage on weekends (Sat/Sun) — outpatient
# clinics that don't run on weekends, etc.
WEEKEND_OK_CATEGORIES: set[str] = {"MOPD"}

LEAVE_DUTY_TYPES = {"MC/EL"}  # counted toward the 10-cap
ANNUAL_LEAVE_TYPES = {"AL"}    # tracked but separate
NON_WORK_DUTY_TYPES = {"OFF", "PC", "AL", "MC/EL", "COURSE", "EOP"}

# EOP policy: a posting tentatively ends 4 calendar months after the start,
# minus 1 day (so 1 Jan + 4mo - 1d = 30 Apr — the last day of posting).
# MC/EL above LEAVE_CAP_DEFAULT pushes the date back day-for-day. Each manual
# postponement (tracked on Officer.postponement_count) shifts it back by
# POSTPONEMENT_DAYS_PER_BUMP days.
POSTING_MONTHS = 4
POSTPONEMENT_DAYS_PER_BUMP = 14
LEAVE_CAP_DEFAULT = 10

# Color per duty_type for the public roster heatmap and chips.
DUTY_COLORS: dict[str, str] = {
    "EH": "#0f766e",      # teal — extended hours
    "OH": "#0ea5e9",      # sky — office hours
    "OC": "#7c3aed",      # violet — on-call
    "TAG": "#f59e0b",     # amber — tagging
    "MOPD": "#06b6d4",    # cyan — outpatient
    "PERI": "#22c55e",    # green — periphery
    "PENDING ED": "#ef4444",  # red — ED
    "OFF": "#94a3b8",     # slate — off
    "PC": "#a78bfa",      # lavender — post-call
    "AL": "#eab308",      # yellow — annual leave
    "MC/EL": "#f43f5e",   # rose — sick / emergency
    "COURSE": "#8b5cf6",  # purple — course
    "EOP": "#64748b",     # slate-deep — end of posting
}


# Seed list — exactly the 37 codes from the Hospital Tengku Permaisuri Norashikin Grouping sheet.
SEED_SHIFTS: list[dict] = [
    {"code": "AL", "hours": 0, "duty_type": "AL", "ward": None},
    {"code": "EH W1", "hours": 14, "duty_type": "EH", "ward": "W1"},
    {"code": "EH W2", "hours": 14, "duty_type": "EH", "ward": "W2"},
    {"code": "EH W3", "hours": 14, "duty_type": "EH", "ward": "W3"},
    {"code": "EH W6", "hours": 14, "duty_type": "EH", "ward": "W6"},
    {"code": "MOPD EH W1", "hours": 14, "duty_type": "MOPD", "ward": "W1"},
    {"code": "MOPD OH W1", "hours": 10, "duty_type": "MOPD", "ward": "W1"},
    {"code": "MOPD EH W2", "hours": 14, "duty_type": "MOPD", "ward": "W2"},
    {"code": "MOPD OH W2", "hours": 10, "duty_type": "MOPD", "ward": "W2"},
    {"code": "MOPD EH W3", "hours": 14, "duty_type": "MOPD", "ward": "W3"},
    {"code": "MOPD OH W3", "hours": 10, "duty_type": "MOPD", "ward": "W3"},
    {"code": "MOPD EH W4", "hours": 14, "duty_type": "MOPD", "ward": "W4"},
    {"code": "MOPD OH W4", "hours": 10, "duty_type": "MOPD", "ward": "W4"},
    {"code": "MOPD EH W6", "hours": 14, "duty_type": "MOPD", "ward": "W6"},
    {"code": "MOPD OH W6", "hours": 10, "duty_type": "MOPD", "ward": "W6"},
    {"code": "OC W1 W72", "hours": 14, "duty_type": "OC", "ward": "W1+W72"},
    {"code": "OC W2 W4", "hours": 14, "duty_type": "OC", "ward": "W2+W4"},
    {"code": "OC W3 W4", "hours": 14, "duty_type": "OC", "ward": "W3+W4"},
    {"code": "OC W6 W72", "hours": 14, "duty_type": "OC", "ward": "W6+W72"},
    {"code": "OFF", "hours": 0, "duty_type": "OFF", "ward": None},
    {"code": "OH W1", "hours": 10, "duty_type": "OH", "ward": "W1"},
    {"code": "OH W2", "hours": 10, "duty_type": "OH", "ward": "W2"},
    {"code": "OH W3", "hours": 10, "duty_type": "OH", "ward": "W3"},
    {"code": "OH W6", "hours": 10, "duty_type": "OH", "ward": "W6"},
    {"code": "PC", "hours": 0, "duty_type": "PC", "ward": None},
    {"code": "P-ED EH", "hours": 14, "duty_type": "PENDING ED", "ward": "ED"},
    {"code": "P-ED OH", "hours": 10, "duty_type": "PENDING ED", "ward": "ED"},
    {"code": "TAG W1", "hours": 15, "duty_type": "TAG", "ward": "W1"},
    {"code": "TAG W2", "hours": 15, "duty_type": "TAG", "ward": "W2"},
    {"code": "TAG W3", "hours": 15, "duty_type": "TAG", "ward": "W3"},
    {"code": "TAG W4", "hours": 15, "duty_type": "TAG", "ward": "W4"},
    {"code": "TAG W6", "hours": 15, "duty_type": "TAG", "ward": "W6"},
    {"code": "PERI EH", "hours": 14, "duty_type": "PERI", "ward": "PERI"},
    {"code": "PERI OH", "hours": 10, "duty_type": "PERI", "ward": "PERI"},
    {"code": "COURSE", "hours": 0, "duty_type": "COURSE", "ward": None},
    {"code": "EOP", "hours": 0, "duty_type": "EOP", "ward": None},
    {"code": "MC/EL", "hours": 0, "duty_type": "MC/EL", "ward": None},
]


def week_start(d: date) -> date:
    """Return Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def week_dates(start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(7)]


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"


def daterange(a: date, b: date) -> Iterable[date]:
    cur = a
    while cur <= b:
        yield cur
        cur += timedelta(days=1)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(d: date, months: int) -> date:
    """Return d + months, clamping the day to the last day of the target month
    (so 31 Jan + 1 month = 28/29 Feb, not an invalid date)."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_tentative_eop(
    posting_start: date,
    mc_count: int,
    postponement_count: int,
    leave_cap: int = LEAVE_CAP_DEFAULT,
) -> date:
    """Tentative EOP from posting start + MC delay + manual postponements.

    Formula: posting_start + POSTING_MONTHS - 1 day
             + max(0, mc_count - leave_cap) days
             + postponement_count * POSTPONEMENT_DAYS_PER_BUMP days
    """
    base = add_months(posting_start, POSTING_MONTHS) - timedelta(days=1)
    leave_delay = max(0, mc_count - leave_cap)
    postpone_delay = max(0, postponement_count) * POSTPONEMENT_DAYS_PER_BUMP
    return base + timedelta(days=leave_delay + postpone_delay)


def safe_secret(section: str, key: str, default):
    """Read st.secrets[section][key] without raising when no secrets file exists.

    Streamlit's st.secrets attribute always exists, but accessing it raises
    StreamlitSecretNotFoundError unless a secrets.toml is present. This helper
    swallows that so pages stay functional in local-dev mode."""
    try:
        import streamlit as st  # local import — keeps this module usable in scripts
        return st.secrets.get(section, {}).get(key, default)
    except Exception:
        return default
