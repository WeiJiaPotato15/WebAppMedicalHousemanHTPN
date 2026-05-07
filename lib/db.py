"""Persistence layer.

Two implementations behind one interface:
- DynamoStore: real DynamoDB (used in production / when AWS creds are present).
- MemoryStore: in-process dicts (used for local dev when AWS creds are absent).

The factory `get_store()` picks one based on whether `st.secrets["aws"]` is configured.
Reads are wrapped with @st.cache_data(ttl=5) at the call sites in pages, not here,
so the same store can be used from scripts (no streamlit context needed).
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
    # Officers
    @abstractmethod
    def list_officers(self) -> list[Officer]: ...
    @abstractmethod
    def upsert_officer(self, o: Officer) -> None: ...
    @abstractmethod
    def delete_officer(self, email: str) -> None: ...

    # Shifts
    @abstractmethod
    def list_shifts(self) -> list[Shift]: ...
    @abstractmethod
    def upsert_shift(self, s: Shift) -> None: ...
    @abstractmethod
    def delete_shift(self, code: str) -> None: ...

    # Assignments
    @abstractmethod
    def get_week_assignments(self, monday: date) -> list[Assignment]: ...
    @abstractmethod
    def get_officer_assignments(self, email: str, start: date, end: date) -> list[Assignment]: ...
    @abstractmethod
    def set_assignment(
        self, email: str, on_date: date, shift_code: str | None, actor_email: str
    ) -> Optional[Assignment]:
        """Upsert (or delete if shift_code is None) and write audit row. Returns new value."""

    # Admins
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

    # Week templates — snapshot of officer row order at the moment a week is "created".
    @abstractmethod
    def get_week_template(self, monday: date) -> Optional[list[str]]:
        """Return the ordered list of officer emails captured when this week was created,
        or None if the week was never explicitly created."""

    @abstractmethod
    def create_week_template(
        self, monday: date, officer_emails: list[str], actor_email: str
    ) -> None:
        """Snapshot officer order for `monday`. Idempotent: rewrites if it already exists.
        Writes an audit row."""

    def has_week_data(self, monday: date) -> bool:
        """True if the given week has either a template or any assignments. Used to gate
        the 'Create roster for next week' button."""
        if self.get_week_template(monday) is not None:
            return True
        return bool(self.get_week_assignments(monday))

    # Bootstrap
    def bootstrap_admin_if_empty(self, email: str, name: str) -> Optional[Admin]:
        """If no admins exist, promote `email` to bootstrap super-admin. Returns the new
        Admin if promoted, else None (door already closed)."""
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
        self._officers: dict[str, Officer] = {}
        self._shifts: dict[str, Shift] = {}
        self._roster: dict[tuple[str, date], Assignment] = {}
        self._templates: dict[date, list[str]] = {}
        self._admins: dict[str, Admin] = {}
        self._audit: dict[str, list[AuditEntry]] = defaultdict(list)
        self._seeded = False
        self._auto_seed(sample_data=seed_sample_data)

    def _auto_seed(self, sample_data: bool = True) -> None:
        if self._seeded:
            return
        from datetime import date as _d, timedelta as _td

        # Always seed the shift dictionary — pages reference it everywhere.
        for s in SEED_SHIFTS:
            self.upsert_shift(Shift(**s))

        if sample_data:
            # 3 sample officers so the local UI has something to render.
            samples = [
                Officer(email="alice@example.com", name="Dr. Alice",
                        posting_start_date=_d(2026, 2, 1), ward_group="W1"),
                Officer(email="ben@example.com", name="Dr. Ben",
                        posting_start_date=_d(2026, 2, 15), ward_group="W2"),
                Officer(email="chen@example.com", name="Dr. Chen",
                        posting_start_date=_d(2026, 3, 1), ward_group="PERI"),
            ]
            for o in samples:
                self.upsert_officer(o)

            # Sample assignments for the current ISO week so the public roster
            # and per-HO stats pages show working visualizations on first load.
            # Written directly to the dict to skip audit-log noise on bootstrap.
            today = _d.today()
            monday = today - _td(days=today.weekday())
            days = [monday + _td(days=i) for i in range(7)]
            weekly = {
                "alice@example.com": ["OH W1", "OH W1", "OH W2", "MC/EL", "OH W1", "OFF", "PC"],
                "ben@example.com":   ["OC W1 W72", "PC", "OH W2", "OH W3", "EH W1", "OFF", "OFF"],
                "chen@example.com":  ["PERI OH", "PERI EH", "OFF", "PERI OH", "OC W3 W4", "PC", "OFF"],
            }
            for email, codes in weekly.items():
                for d, code in zip(days, codes):
                    self._roster[(email, d)] = Assignment(
                        email=email, on_date=d, shift_code=code,
                        modified_by="seed@local", modified_at=now_iso(),
                    )

        self._seeded = True

    # Officers
    def list_officers(self):
        return sorted(self._officers.values(), key=lambda o: o.name)
    def upsert_officer(self, o):
        self._officers[o.email] = o
    def delete_officer(self, email):
        self._officers.pop(email, None)

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
        return [a for (e, d), a in self._roster.items() if monday <= d <= end]
    def get_officer_assignments(self, email, start, end):
        return [a for (e, d), a in self._roster.items() if e == email and start <= d <= end]
    def set_assignment(self, email, on_date, shift_code, actor_email):
        key = (email, on_date)
        before = self._roster.get(key)
        before_code = before.shift_code if before else None
        if shift_code is None:
            self._roster.pop(key, None)
            after = None
        else:
            after = Assignment(
                email=email, on_date=on_date, shift_code=shift_code,
                modified_by=actor_email, modified_at=now_iso(),
            )
            self._roster[key] = after
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="set_assignment",
            target=f"{email}#{on_date.isoformat()}", before=before_code, after=shift_code,
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

    def create_week_template(self, monday, officer_emails, actor_email):
        self._templates[monday] = list(officer_emails)
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="create_week_template",
            target=f"week:{monday.isoformat()}",
            before=None, after=f"{len(officer_emails)} officers",
        ))


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
        # Strip None and convert dates to ISO strings.
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
                email=it["pk"].split("#", 1)[1],
                name=it["name"],
                posting_start_date=date.fromisoformat(it["posting_start_date"]),
                ic_last4=it.get("ic_last4"),
                phone=it.get("phone"),
                active=it.get("active", True),
                ward_group=it.get("ward_group"),
            ))
        return sorted(out, key=lambda o: o.name)

    def upsert_officer(self, o):
        item = self._to_item({
            "pk": f"HO#{o.email}",
            "sk": "PROFILE",
            "name": o.name,
            "posting_start_date": o.posting_start_date,
            "ic_last4": o.ic_last4,
            "phone": o.phone,
            "active": o.active,
            "ward_group": o.ward_group,
        })
        self._t(T_OFFICERS).put_item(Item=item)

    def delete_officer(self, email):
        self._t(T_OFFICERS).delete_item(Key={"pk": f"HO#{email}", "sk": "PROFILE"})

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
        item = self._to_item({
            "pk": f"SHIFT#{s.code}",
            "sk": "MASTER",
            "hours": s.hours,
            "duty_type": s.duty_type,
            "ward": s.ward,
        })
        self._t(T_SHIFTS).put_item(Item=item)

    def delete_shift(self, code):
        self._t(T_SHIFTS).delete_item(Key={"pk": f"SHIFT#{code}", "sk": "MASTER"})

    # Roster
    def get_week_assignments(self, monday):
        from boto3.dynamodb.conditions import Attr
        start = monday.isoformat()
        end = date.fromordinal(monday.toordinal() + 6).isoformat()
        # No GSI on date — we scan with a filter. Volume is tiny (≤30 HO × 7 days = 210 items).
        resp = self._t(T_ROSTER).scan(FilterExpression=Attr("sk").between(start, end))
        out = []
        for it in resp.get("Items", []):
            out.append(Assignment(
                email=it["pk"].split("#", 1)[1],
                on_date=date.fromisoformat(it["sk"]),
                shift_code=it["shift_code"],
                modified_by=it.get("modified_by"),
                modified_at=it.get("modified_at"),
            ))
        return out

    def get_officer_assignments(self, email, start, end):
        from boto3.dynamodb.conditions import Key
        resp = self._t(T_ROSTER).query(
            KeyConditionExpression=Key("pk").eq(f"HO#{email}")
            & Key("sk").between(start.isoformat(), end.isoformat())
        )
        out = []
        for it in resp.get("Items", []):
            out.append(Assignment(
                email=email,
                on_date=date.fromisoformat(it["sk"]),
                shift_code=it["shift_code"],
                modified_by=it.get("modified_by"),
                modified_at=it.get("modified_at"),
            ))
        return out

    def set_assignment(self, email, on_date, shift_code, actor_email):
        key = {"pk": f"HO#{email}", "sk": on_date.isoformat()}
        existing = self._t(T_ROSTER).get_item(Key=key).get("Item")
        before_code = existing.get("shift_code") if existing else None
        if shift_code is None:
            self._t(T_ROSTER).delete_item(Key=key)
            after = None
        else:
            self._t(T_ROSTER).put_item(Item={
                **key,
                "shift_code": shift_code,
                "modified_by": actor_email,
                "modified_at": now_iso(),
            })
            after = Assignment(
                email=email, on_date=on_date, shift_code=shift_code,
                modified_by=actor_email, modified_at=now_iso(),
            )
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="set_assignment",
            target=f"{email}#{on_date.isoformat()}", before=before_code, after=shift_code,
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
            email=email,
            role=it.get("role", "admin"),
            added_by=it.get("added_by"),
            added_at=it.get("added_at"),
            is_bootstrap=it.get("is_bootstrap", False),
        )

    def upsert_admin(self, a):
        self._t(T_ADMINS).put_item(Item=self._to_item({
            "pk": f"ADMIN#{a.email}",
            "sk": "MASTER",
            "role": a.role,
            "added_by": a.added_by,
            "added_at": a.added_at,
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
            "pk": f"AUDIT#{ym}",
            "sk": f"{entry.timestamp}#{entry.actor}",
            "action": entry.action,
            "target": entry.target,
            "before": entry.before,
            "after": entry.after,
        }))

    # Week templates — stored in htpn_roster under pk=WEEK#<monday>, sk=TEMPLATE.
    # The week-assignment scan filters sk by ISO date range, so these rows are
    # invisible to that path even though they share the table.
    def get_week_template(self, monday):
        resp = self._t(T_ROSTER).get_item(Key={
            "pk": f"WEEK#{monday.isoformat()}", "sk": "TEMPLATE",
        })
        item = resp.get("Item")
        if not item:
            return None
        return list(item.get("officer_emails", []))

    def create_week_template(self, monday, officer_emails, actor_email):
        self._t(T_ROSTER).put_item(Item={
            "pk": f"WEEK#{monday.isoformat()}",
            "sk": "TEMPLATE",
            "officer_emails": list(officer_emails),
            "created_by": actor_email,
            "created_at": now_iso(),
        })
        self.add_audit(AuditEntry(
            timestamp=now_iso(), actor=actor_email, action="create_week_template",
            target=f"week:{monday.isoformat()}",
            before=None, after=f"{len(officer_emails)} officers",
        ))


# ---- Factory -------------------------------------------------------------- #

_singleton: Optional[Store] = None


def _read_aws_secrets() -> Optional[dict]:
    """Try Streamlit secrets first, then env vars. Returns None if neither has creds."""
    try:
        import streamlit as st  # type: ignore
        # st.secrets raises StreamlitSecretNotFoundError if no file exists, so guard.
        aws = st.secrets.get("aws", {})
        if aws.get("access_key_id"):
            return {
                "region": aws.get("region", "ap-southeast-1"),
                "access_key_id": aws["access_key_id"],
                "secret_access_key": aws["secret_access_key"],
            }
    except Exception:
        pass
    if os.getenv("AWS_ACCESS_KEY_ID"):
        return {
            "region": os.getenv("AWS_REGION", "ap-southeast-1"),
            "access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
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
    """Force re-creation. Tests call this to swap implementations."""
    global _singleton
    _singleton = None
