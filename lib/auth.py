"""Auth: Google OAuth via Streamlit's native st.login + DynamoDB allowlist.

Bootstrap rule: the very first Google login becomes a `super` admin if the admins
table is empty. Once even one admin row exists, unknown emails are denied — i.e.
the door auto-locks. Operators can disable bootstrap entirely via secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import streamlit as st

from .constants import safe_secret
from .db import get_store
from .models import Admin


@dataclass
class CurrentUser:
    email: str
    name: str
    is_admin: bool
    is_super: bool
    bootstrap_eligible: bool  # True iff admins table is empty AND bootstrap not disabled


def _bootstrap_disabled() -> bool:
    return bool(safe_secret("app", "disable_bootstrap", False))


def _get_oauth_user() -> Optional[tuple[str, str]]:
    """Return (email, name) of the logged-in Google user, or None.

    Streamlit 1.42+ exposes st.user with .is_logged_in / .email / .name when
    [auth] secrets are configured. We tolerate older runtimes by returning None.
    """
    try:
        if hasattr(st, "user") and getattr(st.user, "is_logged_in", False):
            email = getattr(st.user, "email", None)
            name = getattr(st.user, "name", None) or (email.split("@")[0] if email else "Unknown")
            if email:
                return email, name
    except Exception:
        return None
    return None


def current_user() -> Optional[CurrentUser]:
    """Return current logged-in user with role flags, or None if not logged in."""
    pair = _get_oauth_user()
    if not pair:
        return None
    email, name = pair
    store = get_store()
    admins = store.list_admins()
    admin = next((a for a in admins if a.email == email), None)
    bootstrap_eligible = (not admins) and (not _bootstrap_disabled())
    return CurrentUser(
        email=email,
        name=name,
        is_admin=admin is not None,
        is_super=bool(admin and admin.role == "super"),
        bootstrap_eligible=bootstrap_eligible,
    )


def login_button(label: str = "Sign in with Google") -> None:
    """Render the Google sign-in button. No-op if already logged in.

    If [auth] secrets are not configured (typical local-dev), show a helpful
    info banner instead of a non-functional button."""
    if _get_oauth_user():
        return
    # Streamlit's per-provider credentials live in [auth.google], a nested
    # table, so we look two levels deep here.
    try:
        auth_configured = bool(
            (st.secrets.get("auth", {}).get("google", {}) or {}).get("client_id")
        )
    except Exception:
        auth_configured = False
    if not auth_configured:
        st.info(
            "Google sign-in is not configured for this environment.\n\n"
            "**Local dev**: copy `.streamlit/secrets.toml.example` to "
            "`.streamlit/secrets.toml` and fill in the `[auth]` section, then restart Streamlit.\n\n"
            "**Deployed app**: the operator needs to add `[auth]` to "
            "Settings → Secrets in Streamlit Cloud."
        )
        return
    if st.button(label, type="primary"):
        st.login("google")  # Streamlit 1.42+ — provider name only; no label kwarg


def logout_button(label: str = "Sign out") -> None:
    user = _get_oauth_user()
    if not user:
        return
    if st.button(label, type="secondary"):
        try:
            st.logout()
        except Exception:
            pass


def claim_bootstrap_if_eligible(u: CurrentUser) -> Optional[Admin]:
    """If the admins table is empty, promote this user to super-admin.
    Idempotent — a second caller will see the table is no longer empty and get None."""
    if not u.bootstrap_eligible:
        return None
    return get_store().bootstrap_admin_if_empty(u.email, u.name)


def require_admin() -> CurrentUser:
    """Page guard. Renders login UI and stops the page if not an admin."""
    u = current_user()
    if u is None:
        st.title("🔒 Admin login required")
        st.write("This page is for House Officer leaders only.")
        login_button()
        st.stop()
    if not u.is_admin:
        if u.bootstrap_eligible:
            st.warning(
                "No admins exist yet. Click the button below to claim the bootstrap "
                "super-admin role for this email."
            )
            if st.button(f"Claim super-admin role for {u.email}", type="primary"):
                claim_bootstrap_if_eligible(u)
                st.success("You are now the super admin. Refreshing…")
                st.rerun()
            st.stop()
        st.error(
            f"Access denied. {u.email} is not an authorized admin. "
            "Ask the bootstrap super-admin to add you on the Admins page."
        )
        logout_button()
        st.stop()
    return u  # type: ignore[return-value]


def require_super() -> CurrentUser:
    u = require_admin()
    if not u.is_super:
        st.error("Super-admin role required for this action.")
        st.stop()
    return u
