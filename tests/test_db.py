"""Sanity checks on MemoryStore. DynamoStore is exercised by integration tests
(not run on every commit) since it requires real AWS credentials."""
from __future__ import annotations

from datetime import date

from lib.constants import SEED_SHIFTS
from lib.db import MemoryStore
from lib.models import Officer


def fresh_store() -> MemoryStore:
    return MemoryStore()


def test_seeds_shifts_on_construction():
    s = fresh_store()
    assert len(s.list_shifts()) == len(SEED_SHIFTS)


def test_set_and_get_assignment():
    s = fresh_store()
    s.upsert_officer(Officer(email="a@x.com", name="A", posting_start_date=date(2026, 1, 1)))
    s.set_assignment("a@x.com", date(2026, 5, 4), "OH W1", "leader@x.com")
    week = s.get_week_assignments(date(2026, 5, 4))
    assert len(week) == 1
    assert week[0].shift_code == "OH W1"
    assert week[0].modified_by == "leader@x.com"


def test_overwrite_creates_audit():
    from datetime import datetime as _dt
    s = fresh_store()
    s.upsert_officer(Officer(email="a@x.com", name="A", posting_start_date=date(2026, 1, 1)))
    s.set_assignment("a@x.com", date(2026, 5, 4), "OH W1", "x@x.com")
    s.set_assignment("a@x.com", date(2026, 5, 4), "OH W2", "y@x.com")
    # Audit rows are bucketed by the UTC month of the write, not the assignment date.
    current_ym = _dt.utcnow().strftime("%Y-%m")
    audit = s.list_audit(current_ym)
    assert sum(1 for e in audit if e.action == "set_assignment") >= 2


def test_delete_assignment():
    s = fresh_store()
    s.upsert_officer(Officer(email="a@x.com", name="A", posting_start_date=date(2026, 1, 1)))
    s.set_assignment("a@x.com", date(2026, 5, 4), "OH W1", "x@x.com")
    s.set_assignment("a@x.com", date(2026, 5, 4), None, "x@x.com")
    assert s.get_week_assignments(date(2026, 5, 4)) == []


def test_bootstrap_admin_only_once():
    s = fresh_store()
    a1 = s.bootstrap_admin_if_empty("alice@x.com", "Alice")
    assert a1 is not None and a1.role == "super" and a1.is_bootstrap is True
    a2 = s.bootstrap_admin_if_empty("bob@x.com", "Bob")
    assert a2 is None  # door is closed
    assert len(s.list_admins()) == 1
