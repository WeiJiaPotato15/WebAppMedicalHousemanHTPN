"""Pydantic models for all persisted entities."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


class Officer(BaseModel):
    email: str  # primary key
    name: str
    posting_start_date: date
    ic_last4: Optional[str] = None
    phone: Optional[str] = None
    active: bool = True


class Shift(BaseModel):
    code: str  # primary key, e.g. "EH W1"
    hours: int  # 0, 10, 14, 15, ...
    duty_type: str  # "EH", "OH", "OC", "TAG", "MOPD", "PERI", "PENDING ED", "OFF", "PC", "AL", "MC/EL", ...
    ward: Optional[str] = None  # "W1", "W2", "PERI", "ED", "W1+W72", ...


class Assignment(BaseModel):
    """One cell in the roster grid: who is on what on which date."""
    email: str
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
