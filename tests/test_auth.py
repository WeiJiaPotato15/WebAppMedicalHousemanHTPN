"""Auth tests: bootstrap edge cases. The OAuth side requires Streamlit runtime
and is exercised manually."""
from __future__ import annotations

from lib.db import MemoryStore


def test_bootstrap_idempotent_when_already_admin():
    s = MemoryStore()
    s.bootstrap_admin_if_empty("alice@x.com", "Alice")
    # second call returns None
    assert s.bootstrap_admin_if_empty("alice@x.com", "Alice") is None


def test_existing_admin_blocks_bootstrap():
    s = MemoryStore()
    s.bootstrap_admin_if_empty("alice@x.com", "Alice")
    # different user cannot bootstrap once any admin exists
    res = s.bootstrap_admin_if_empty("eve@x.com", "Eve")
    assert res is None
    emails = {a.email for a in s.list_admins()}
    assert "eve@x.com" not in emails
