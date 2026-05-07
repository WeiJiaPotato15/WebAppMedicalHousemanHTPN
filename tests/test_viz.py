"""Plotly figures should at least construct without raising on small datasets."""
from __future__ import annotations

from datetime import date

from lib.constants import SEED_SHIFTS
from lib.db import MemoryStore
from lib.models import Officer, Shift
from lib.viz import (
    assignments_df,
    count_leaves,
    days_in_posting,
    hours_per_staff_figure,
    leave_progress_figure,
    staff_per_station_per_day_figure,
    station_mix_donut,
    total_hours,
    week_grid_figure,
)


_IC_A = "990101010001"
_IC_B = "920202020002"


def _populated_store() -> MemoryStore:
    s = MemoryStore(seed_sample_data=False)
    s.upsert_officer(Officer(ic_number=_IC_A, name="A", posting_start_date=date(2026, 1, 1)))
    s.upsert_officer(Officer(ic_number=_IC_B, name="B", posting_start_date=date(2026, 1, 1)))
    monday = date(2026, 5, 4)
    s.set_assignment(_IC_A, monday, "OH W1", "x")
    s.set_assignment(_IC_A, date(2026, 5, 5), "MC/EL", "x")
    s.set_assignment(_IC_B, monday, "OC W1 W72", "x")
    return s


def test_week_grid_renders():
    s = _populated_store()
    monday = date(2026, 5, 4)
    a = s.get_week_assignments(monday)
    df = assignments_df(a, s.list_shifts(), s.list_officers())
    fig = week_grid_figure(df, monday)
    assert fig is not None


def test_coverage_chart():
    s = _populated_store()
    a = s.get_week_assignments(date(2026, 5, 4))
    df = assignments_df(a, s.list_shifts(), s.list_officers())
    fig = staff_per_station_per_day_figure(df, min_per_ward=1)
    assert fig is not None


def test_hours_chart():
    s = _populated_store()
    a = s.get_week_assignments(date(2026, 5, 4))
    df = assignments_df(a, s.list_shifts(), s.list_officers())
    fig = hours_per_staff_figure(df)
    assert fig is not None


def test_donut_and_progress():
    s = _populated_store()
    a = s.get_officer_assignments(_IC_A, date(2026, 5, 4), date(2026, 5, 10))
    df = assignments_df(a, s.list_shifts(), s.list_officers())
    assert leave_progress_figure(count_leaves(df), 10) is not None
    assert station_mix_donut(df) is not None


def test_total_hours_and_posting_days():
    s = _populated_store()
    me = next(o for o in s.list_officers() if o.ic_number == _IC_A)
    a = s.get_officer_assignments(_IC_A, date(2026, 1, 1), date(2026, 5, 31))
    df = assignments_df(a, s.list_shifts(), s.list_officers())
    assert total_hours(df) == 10  # OH W1=10, MC/EL=0
    assert days_in_posting(me, today=date(2026, 5, 7)) == (date(2026, 5, 7) - date(2026, 1, 1)).days


def test_seed_count_matches():
    assert len(SEED_SHIFTS) == 37
    # Quick spot check: every code is unique
    codes = [s["code"] for s in SEED_SHIFTS]
    assert len(set(codes)) == len(codes)
    # Every duty type is non-empty
    assert all(s["duty_type"] for s in SEED_SHIFTS)
    # Hours are reasonable
    assert all(s["hours"] in (0, 10, 14, 15) for s in SEED_SHIFTS)
    # And every shift can be hydrated as a Shift model
    for s in SEED_SHIFTS:
        Shift(**s)
