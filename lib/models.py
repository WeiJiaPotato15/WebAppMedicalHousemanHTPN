"""Pydantic models for all persisted entities."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


class Officer(BaseModel):
    ic_number: str  # primary key — Malaysian IC, e.g. "990101015555"
    name: str
    posting_start_date: date
    phone: Optional[str] = None
    active: bool = True
    # Primary ward for grouping in the roster grid (e.g. "W1", "W2", "MOPD",
    # "PERI"). Mirrors the Google Sheet's row groupings. None = ungrouped.
    ward_group: Optional[str] = None
    # Which medical posting this is for the HO — typically 1 to 6.
    posting_number: Optional[int] = None


class Shift(BaseModel):
    code: str  # primary key, e.g. "EH W1"
    hours: int  # 0, 10, 14, 15, ...
    duty_type: str  # "EH", "OH", "OC", "TAG", "MOPD", "PERI", "PENDING ED", "OFF", "PC", "AL", "MC/EL", ...
    ward: Optional[str] = None  # "W1", "W2", "PERI", "ED", "W1+W72", ...
    # Per-shift color override. Hex string like "#0f766e". When None, the
    # heatmap falls back to constants.DUTY_COLORS[duty_type].
    color: Optional[str] = None


class Assignment(BaseModel):
    """One cell in the roster grid: who is on what on which date."""
    ic_number: str
    on_date: date
    shift_code: str
    modified_by: Optional[str] = None
    modified_at: Optional[str] = None  # ISO8601 UTC


AdminRole = Literal["super", "admin"]


class Admin(BaseModel):
    email: str
    role: AdminRole = "admin"
    added_by: Optional[str] = None
    added_at: Optional[str] = None
    is_bootstrap: bool = False


class AuditEntry(BaseModel):
    timestamp: str   # ISO8601 UTC
    actor: str       # email
    action: str      # "set_assignment", "add_admin", "remove_admin", "upsert_officer", "upsert_shift", ...
    target: str      # e.g. "alice@x.com#2026-05-04" or "shift:EH W1"
    before: Optional[str] = None
    after: Optional[str] = None
