"""Persistence layer.

Two implementations behind one interface:
- DynamoStore: real DynamoDB (used in production / when AWS creds are present).
- MemoryStore: in-process dicts (used for local dev when AWS creds are absent).

The factory `get_store()` picks one based on whether `st.secrets["aws"]` is configured.
Reads are wrapped with @st.cache_data(ttl=5) at the call sites in pages, not here,
so the same store can be used from scripts (no streamlit context needed).

Note on identity: Officer + Assignment are keyed by `ic_number` (Malaysian IC).
Admin records are keyed by `email` (admin's Google login). Two different identity
spaces — keep them straight.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date
from typing import Optional

from .constants import SEED_SHIFTS, now_iso
from .models import Admin, Assignment, AuditEntry, Officer, Shift

# ---- Table names ---------------------------------------------------------- #

T_ROSTER = "htpn_roster"
T_OFFICERS = "htpn_officers"
T_SHIFTS = "htpn_shifts"
T_ADMINS = "htpn_admins"
T_AUDIT = "htpn_audit"
ALL_TABLES = (T_ROSTER, T_OFFICERS, T_SHIFTS, T_ADMINS, T_AUDIT)


# ---- Abstract interface --------------------------------------------------- #

class Store(ABC):
    # Officers (keyed by ic_number)
    @abstractmethod
    def list_officers(self) -> list[Officer]: ...
    @abstractmethod
    def upsert_officer(self, o: Officer) -> None: ...
    @abstractmethod
    def delete_officer(self, ic_number: str) -> None: ...

    # Shifts
    @abstractmethod
    def list_shifts(self) -> list[Shift]: ...
    @abstractmethod
    def upsert_shift(self, s: Shift) -> None: ...
    @abstractmethod
    def delete_shift(self, code: str) -> None: ...

    # Assignments (keyed by ic_number + date)
    @abstractmethod
    def get_week_assignments(self, monday: date) -> list[Assignment]: ...
    @abstractmethod
    def get_officer_assignments(self, ic_number: str, start: date, end: date) -> list[Assignment]: ...
    @abstractmethod
    def set_assignment(
        self, ic_number: str, on_date: date, shift_code: str | None, actor_email: str
    ) -> Optional[Assignment]:
        """Upsert (or delete if shift_code is None) and write audit row. Returns new value."""

    # Admins (keyed by Google email — admin identity, not officer identity)
    @abstractmethod
    def list_admins(self) -> list[Admin]: ...
    @abstractmethod
    def get_admin(self, email: str) -> Optional[Admin]: ...
    @abstractmethod
    def upsert_admin(self, a: Admin) -> None: ...
    @abstractmethod
    def delete_admin(self, email: str) -> None: ...

    # Audit
    @abstractmethod
    def list_audit(self, year_month: str, limit: int = 200) -> list[AuditEntry]: ...
    @abstractmethod
    def add_audit(self, entry: AuditEntry) -> None: ...

    # End-of-posting dates. Derived from assignments — no separate stored field.
    def list_eop_dates(self) -> dict[str, date]:
        """Return {ic_number: earliest_EOP_date} for every officer with at least
        one assignment whose shift has duty_type == "EOP". Derived live, so always
        consistent with the current roster — no sync logic needed."""
        eop_codes = {s.code for s in self.list_shifts() if s.duty_type == "EOP"}
        if not eop_codes:
            return {}
        from datetime import timedelta
        today = date.today()
        start = today - timedelta(days=730)
        end = today + timedelta(days=365)
        out: dict[str, date] = {}
        for o in self.list_officers():
            for a in self.get_officer_assignments(o.ic_number, start, end):
                if a.shift_code in eop_codes:
                    cur = out.get(o.ic_number)
                    if cur is None or a.on_date < cur:
                        out[o.ic_number] = a.on_date
        return out

    # Week templates — snapshot of officer row order at week creation.
    @abstractmethod
    def get_week_template(self, monday: date) -> Optional[list[str]]:
        """Return the ordered list of officer ic_numbers captured when this week
        was created, or None if the week was never explicitly created."""

    @abstractmethod
    def create_week_template(
        self, monday: date, officer_ic_numbers: list[str], actor_email: str
    ) -> None:
        """Snapshot officer order for `monday`. Idempotent. Writes an audit row."""

    def has_week_data(self, monday: date) -> bool:
        if self.get_week_template(monday) is not None:
            return True
        return bool(self.get_week_assignments(monday))

    # Bootstrap (admin allowlist)
    def bootstrap_admin_if_empty(self, email: str, name: str) -> Optional[Admin]:
        if self.list_admins():
            return None
        a = Admin(
            email=email,
            role="super",
            added_by="bootstrap",
            added_at=now_iso(),
            is_bootstrap=True,
        )
        self.upsert_admin(a)
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=email, action="bootstrap_admin",
            target=f"admin:{email}", before=None, after=name,
        ))
        return a


# ---- In-memory implementation -------------------------------------------- #

class MemoryStore(Store):
    """Single-process dict store. Used when no AWS creds are configured."""

    def __init__(self, seed_sample_data: bool = True) -> None:
        self._officers: dict[str, Officer] = {}  # keyed by ic_number
        self._shifts: dict[str, Shift] = {}
        self._roster: dict[tuple[str, date], Assignment] = {}  # (ic_number, date) -> Assignment
        self._templates: dict[date, list[str]] = {}  # monday -> [ic_numbers]
        self._admins: dict[str, Admin] = {}  # keyed by email
        self._audit: dict[str, list[AuditEntry]] = defaultdict(list)
        self._seeded = False
        self._auto_seed(sample_data=seed_sample_data)

    def _auto_seed(self, sample_data: bool = True) -> None:
        if self._seeded:
            return
        from datetime import date as _d, timedelta as _td

        for s in SEED_SHIFTS:
            self.upsert_shift(Shift(**s))

        if sample_data:
            samples = [
                Officer(ic_number="990101015555", name="Dr. Alice",
                        posting_start_date=_d(2026, 2, 1), ward_group="W1"),
                Officer(ic_number="920202075555", name="Dr. Ben",
                        posting_start_date=_d(2026, 2, 15), ward_group="W2"),
                Officer(ic_number="910303095555", name="Dr. Chen",
                        posting_start_date=_d(2026, 3, 1), ward_group="PERI"),
            ]
            for o in samples:
                self.upsert_officer(o)

            today = _d.today()
            monday = today - _td(days=today.weekday())
            days = [monday + _td(days=i) for i in range(7)]
            weekly = {
                "990101015555": ["OH W1", "OH W1", "OH W2", "MC/EL", "OH W1", "OFF", "PC"],
                "920202075555": ["OC W1 W72", "PC", "OH W2", "OH W3", "EH W1", "OFF", "OFF"],
                "910303095555": ["PERI OH", "PERI EH", "OFF", "PERI OH", "OC W3 W4", "PC", "OFF"],
            }
            for ic, codes in weekly.items():
                for d, code in zip(days, codes):
                    self._roster[(ic, d)] = Assignment(
                        ic_number=ic, on_date=d, shift_code=code,
                        modified_by="seed@local", modified_at=now_iso(),
                    )

        self._seeded = True

    # Officers
    def list_officers(self):
        return sorted(self._officers.values(), key=lambda o: o.name)
    def upsert_officer(self, o):
        self._officers[o.ic_number] = o
    def delete_officer(self, ic_number):
        self._officers.pop(ic_number, None)

    # Shifts
    def list_shifts(self):
        return sorted(self._shifts.values(), key=lambda s: s.code)
    def upsert_shift(self, s):
        self._shifts[s.code] = s
    def delete_shift(self, code):
        self._shifts.pop(code, None)

    # Roster
    def get_week_assignments(self, monday):
        end = date.fromordinal(monday.toordinal() + 6)
        return [a for (ic, d), a in self._roster.items() if monday <= d <= end]
    def get_officer_assignments(self, ic_number, start, end):
        return [a for (ic, d), a in self._roster.items() if ic == ic_number and start <= d <= end]
    def set_assignment(self, ic_number, on_date, shift_code, actor_email):
        key = (ic_number, on_date)
        before = self._roster.get(key)
        before_code = before.shift_code if before else None
        if shift_code is None:
            self._roster.pop(key, None)
            after = None
        else:
            after = Assignment(
                ic_number=ic_number, on_date=on_date, shift_code=shift_code,
                modified_by=actor_email, modified_at=now_iso(),
            )
            self._roster[key] = after
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="set_assignment",
            target=f"{ic_number}#{on_date.isoformat()}", before=before_code, after=shift_code,
        ))
        return after

    # Admins
    def list_admins(self):
        return sorted(self._admins.values(), key=lambda a: a.email)
    def get_admin(self, email):
        return self._admins.get(email)
    def upsert_admin(self, a):
        self._admins[a.email] = a
    def delete_admin(self, email):
        self._admins.pop(email, None)

    # Audit
    def list_audit(self, year_month, limit=200):
        return list(reversed(self._audit.get(year_month, [])))[:limit]
    def add_audit(self, entry):
        ym = entry.timestamp[:7]
        self._audit[ym].append(entry)

    # Week templates
    def get_week_template(self, monday):
        return list(self._templates[monday]) if monday in self._templates else None

    def create_week_template(self, monday, officer_ic_numbers, actor_email):
        self._templates[monday] = list(officer_ic_numbers)
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="create_week_template",
            target=f"week:{monday.isoformat()}",
            before=None, after=f"{len(officer_ic_numbers)} officers",
        ))

    # EOP — direct dict scan
    def list_eop_dates(self):
        eop_codes = {s.code for s in self.list_shifts() if s.duty_type == "EOP"}
        if not eop_codes:
            return {}
        out: dict[str, date] = {}
        for (ic, on_date), a in self._roster.items():
            if a.shift_code not in eop_codes:
                continue
            cur = out.get(ic)
            if cur is None or on_date < cur:
                out[ic] = on_date
        return out


# ---- DynamoDB implementation --------------------------------------------- #

class DynamoStore(Store):
    """Real DynamoDB. Idempotent on writes. Uses provisioned 25/25 RCU/WCU tables."""

    def __init__(self, region: str, access_key_id: str, secret_access_key: str) -> None:
        import boto3  # local import — keep optional for environments without it
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _t(self, name: str):
        return self._ddb.Table(name)

    @staticmethod
    def _to_item(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if v is None:
                continue
            if isinstance(v, date):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out

    # Officers
    def list_officers(self):
        resp = self._t(T_OFFICERS).scan()
        out = []
        for it in resp.get("Items", []):
            out.append(Officer(
                ic_number=it["pk"].split("#", 1)[1],
                name=it["name"],
                posting_start_date=date.fromisoformat(it["posting_start_date"]),
                phone=it.get("phone"),
                active=it.get("active", True),
                ward_group=it.get("ward_group"),
            ))
        return sorted(out, key=lambda o: o.name)

    def upsert_officer(self, o):
        item = self._to_item({
            "pk": f"HO#{o.ic_number}",
            "sk": "PROFILE",
            "name": o.name,
            "posting_start_date": o.posting_start_date,
            "phone": o.phone,
            "active": o.active,
            "ward_group": o.ward_group,
        })
        self._t(T_OFFICERS).put_item(Item=item)

    def delete_officer(self, ic_number):
        self._t(T_OFFICERS).delete_item(Key={"pk": f"HO#{ic_number}", "sk": "PROFILE"})

    # Shifts
    def list_shifts(self):
        resp = self._t(T_SHIFTS).scan()
        out = []
        for it in resp.get("Items", []):
            out.append(Shift(
                code=it["pk"].split("#", 1)[1],
                hours=int(it["hours"]),
                duty_type=it["duty_type"],
                ward=it.get("ward"),
            ))
        return sorted(out, key=lambda s: s.code)

    def upsert_shift(self, s):
        self._t(T_SHIFTS).put_item(Item=self._to_item({
            "pk": f"SHIFT#{s.code}", "sk": "MASTER",
            "hours": s.hours, "duty_type": s.duty_type, "ward": s.ward,
        }))

    def delete_shift(self, code):
        self._t(T_SHIFTS).delete_item(Key={"pk": f"SHIFT#{code}", "sk": "MASTER"})

    # Roster
    def get_week_assignments(self, monday):
        from boto3.dynamodb.conditions import Attr
        start = monday.isoformat()
        end = date.fromordinal(monday.toordinal() + 6).isoformat()
        resp = self._t(T_ROSTER).scan(FilterExpression=Attr("sk").between(start, end))
        out = []
        for it in resp.get("Items", []):
            if not it.get("pk", "").startswith("HO#"):
                continue
            out.append(Assignment(
                ic_number=it["pk"].split("#", 1)[1],
                on_date=date.fromisoformat(it["sk"]),
                shift_code=it["shift_code"],
                modified_by=it.get("modified_by"),
                modified_at=it.get("modified_at"),
            ))
        return out

    def get_officer_assignments(self, ic_number, start, end):
        from boto3.dynamodb.conditions import Key
        resp = self._t(T_ROSTER).query(
            KeyConditionExpression=Key("pk").eq(f"HO#{ic_number}")
            & Key("sk").between(start.isoformat(), end.isoformat())
        )
        out = []
        for it in resp.get("Items", []):
            out.append(Assignment(
                ic_number=ic_number,
                on_date=date.fromisoformat(it["sk"]),
                shift_code=it["shift_code"],
                modified_by=it.get("modified_by"),
                modified_at=it.get("modified_at"),
            ))
        return out

    def set_assignment(self, ic_number, on_date, shift_code, actor_email):
        key = {"pk": f"HO#{ic_number}", "sk": on_date.isoformat()}
        existing = self._t(T_ROSTER).get_item(Key=key).get("Item")
        before_code = existing.get("shift_code") if existing else None
        if shift_code is None:
            self._t(T_ROSTER).delete_item(Key=key)
            after = None
        else:
            self._t(T_ROSTER).put_item(Item={
                **key, "shift_code": shift_code,
                "modified_by": actor_email, "modified_at": now_iso(),
            })
            after = Assignment(
                ic_number=ic_number, on_date=on_date, shift_code=shift_code,
                modified_by=actor_email, modified_at=now_iso(),
            )
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="set_assignment",
            target=f"{ic_number}#{on_date.isoformat()}", before=before_code, after=shift_code,
        ))
        return after

    # Admins
    def list_admins(self):
        resp = self._t(T_ADMINS).scan()
        out = []
        for it in resp.get("Items", []):
            out.append(Admin(
                email=it["pk"].split("#", 1)[1],
                role=it.get("role", "admin"),
                added_by=it.get("added_by"),
                added_at=it.get("added_at"),
                is_bootstrap=it.get("is_bootstrap", False),
            ))
        return sorted(out, key=lambda a: a.email)

    def get_admin(self, email):
        it = self._t(T_ADMINS).get_item(Key={"pk": f"ADMIN#{email}", "sk": "MASTER"}).get("Item")
        if not it:
            return None
        return Admin(
            email=email, role=it.get("role", "admin"),
            added_by=it.get("added_by"), added_at=it.get("added_at"),
            is_bootstrap=it.get("is_bootstrap", False),
        )

    def upsert_admin(self, a):
        self._t(T_ADMINS).put_item(Item=self._to_item({
            "pk": f"ADMIN#{a.email}", "sk": "MASTER",
            "role": a.role, "added_by": a.added_by, "added_at": a.added_at,
            "is_bootstrap": a.is_bootstrap,
        }))

    def delete_admin(self, email):
        self._t(T_ADMINS).delete_item(Key={"pk": f"ADMIN#{email}", "sk": "MASTER"})

    # Audit
    def list_audit(self, year_month, limit=200):
        from boto3.dynamodb.conditions import Key
        resp = self._t(T_AUDIT).query(
            KeyConditionExpression=Key("pk").eq(f"AUDIT#{year_month}"),
            ScanIndexForward=False,
            Limit=limit,
        )
        out = []
        for it in resp.get("Items", []):
            ts, actor = it["sk"].split("#", 1)
            out.append(AuditEntry(
                timestamp=ts, actor=actor,
                action=it["action"], target=it["target"],
                before=it.get("before"), after=it.get("after"),
            ))
        return out

    def add_audit(self, entry):
        ym = entry.timestamp[:7]
        self._t(T_AUDIT).put_item(Item=self._to_item({
            "pk": f"AUDIT#{ym}", "sk": f"{entry.timestamp}#{entry.actor}",
            "action": entry.action, "target": entry.target,
            "before": entry.before, "after": entry.after,
        }))

    # Week templates — stored in htpn_roster under pk=WEEK#<monday>, sk=TEMPLATE.
    def get_week_template(self, monday):
        resp = self._t(T_ROSTER).get_item(Key={
            "pk": f"WEEK#{monday.isoformat()}", "sk": "TEMPLATE",
        })
        item = resp.get("Item")
        if not item:
            return None
        return list(item.get("officer_ic_numbers", item.get("officer_emails", [])))

    def create_week_template(self, monday, officer_ic_numbers, actor_email):
        self._t(T_ROSTER).put_item(Item={
            "pk": f"WEEK#{monday.isoformat()}",
            "sk": "TEMPLATE",
            "officer_ic_numbers": list(officer_ic_numbers),
            "created_by": actor_email,
            "created_at": now_iso(),
        })
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="create_week_template",
            target=f"week:{monday.isoformat()}",
            before=None, after=f"{len(officer_ic_numbers)} officers",
        ))

    # EOP — single scan + Python-side filter (table is small)
    def list_eop_dates(self):
        eop_codes = {s.code for s in self.list_shifts() if s.duty_type == "EOP"}
        if not eop_codes:
            return {}
        resp = self._t(T_ROSTER).scan()
        out: dict[str, date] = {}
        for it in resp.get("Items", []):
            if not it.get("pk", "").startswith("HO#"):
                continue
            if it.get("shift_code") not in eop_codes:
                continue
            try:
                on_date = date.fromisoformat(it["sk"])
            except (ValueError, KeyError):
                continue
            ic = it["pk"].split("#", 1)[1]
            cur = out.get(ic)
            if cur is None or on_date < cur:
                out[ic] = on_date
        return out


# ---- Factory -------------------------------------------------------------- #

_singleton: Optional[Store] = None


def _is_placeholder(v: str) -> bool:
    """True if the value looks like an unfilled secrets-template placeholder."""
    return (not v) or v.startswith("REPLACE_WITH") or v.startswith("REPLACE-WITH")


def _read_aws_secrets() -> Optional[dict]:
    """Return AWS creds if configured with real values, else None.
    Template placeholders (REPLACE_WITH_*) are treated as 'not configured' so
    the factory transparently falls back to MemoryStore in dev."""
    try:
        import streamlit as st  # type: ignore
        aws = st.secrets.get("aws", {})
        key_id = aws.get("access_key_id", "")
        secret = aws.get("secret_access_key", "")
        if key_id and secret and not _is_placeholder(key_id) and not _is_placeholder(secret):
            return {
                "region": aws.get("region", "ap-southeast-1"),
                "access_key_id": key_id,
                "secret_access_key": secret,
            }
    except Exception:
        pass
    env_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    env_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if env_key and env_secret and not _is_placeholder(env_key) and not _is_placeholder(env_secret):
        return {
            "region": os.getenv("AWS_REGION", "ap-southeast-1"),
            "access_key_id": env_key,
            "secret_access_key": env_secret,
        }
    return None


def get_store() -> Store:
    """Return a singleton Store. DynamoStore if AWS creds available, else MemoryStore."""
    global _singleton
    if _singleton is not None:
        return _singleton
    creds = _read_aws_secrets()
    if creds:
        _singleton = DynamoStore(**creds)
    else:
        _singleton = MemoryStore()
    return _singleton


def reset_store_for_tests() -> None:
    global _singleton
    _singleton = None
