"""Lightweight presence tracking: who is currently on an admin page.

Streamlit Community Cloud runs a single replica per app, so an in-process dict
keyed by email is sufficient. If we ever scale out, swap this for a DynamoDB
table with TTL=30s.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import streamlit as st

PRESENCE_TTL_S = 30


@dataclass
class Heartbeat:
    email: str
    name: str
    page: str
    last_seen: float  # epoch seconds


@st.cache_resource
def _registry() -> dict[str, Heartbeat]:
    """Process-wide registry. cache_resource keeps it across reruns and sessions."""
    return {}


def beat(email: str, name: str, page: str) -> None:
    _registry()[email] = Heartbeat(email=email, name=name, page=page, last_seen=time.time())


def active(exclude_email: Optional[str] = None) -> list[Heartbeat]:
    now = time.time()
    out = [
        h for h in _registry().values()
        if (now - h.last_seen) < PRESENCE_TTL_S and h.email != exclude_email
    ]
    return sorted(out, key=lambda h: h.last_seen, reverse=True)


def render_sidebar(current_email: str) -> None:
    others = active(exclude_email=current_email)
    if not others:
        st.sidebar.caption("👤 Only you are editing right now")
        return
    st.sidebar.markdown("### 👥 Also editing")
    for h in others:
        ago = max(0, int(time.time() - h.last_seen))
        st.sidebar.caption(f"• **{h.name}** — {h.page} · {ago}s ago")
