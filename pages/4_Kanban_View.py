"""Admin: kanban-by-day drag-and-drop view (secondary editor).

Each day is a column listing officers grouped by their assigned shift code.
Reorder within a column to express priority/swap intent; the change is recorded
as an audit entry but does not by itself reassign — use Edit Roster for code
changes. This view is most useful for visual rebalancing during sudden changes.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_sortables import sort_items

from lib.auth import require_admin
from lib.constants import DUTY_COLORS, week_dates, week_label, week_start
from lib.db import get_store
from lib.presence import beat, render_sidebar

st.set_page_config(page_title="Kanban — HTPN", page_icon="🎯", layout="wide")
PAGE_NAME = "Kanban"


def main() -> None:
    user = require_admin()
    st_autorefresh(interval=5_000, key="kanban_refresh")
    beat(user.email, user.name, PAGE_NAME)
    render_sidebar(user.email)

    st.title("🎯 Kanban view")
    st.caption(
        "Visual rebalance of the week. Drag officer chips between shifts; saves on release. "
        "For free-text edits use the Edit Roster page."
    )

    if "kanban_monday" not in st.session_state:
        st.session_state.kanban_monday = week_start(date.today())

    cprev, clabel, cnext = st.columns([1, 5, 1])
    if cprev.button("◀ Prev"):
        st.session_state.kanban_monday -= timedelta(days=7)
    if cnext.button("Next ▶"):
        st.session_state.kanban_monday += timedelta(days=7)
    monday = st.session_state.kanban_monday
    clabel.subheader(f"Week of {week_label(monday)}")

    store = get_store()
    officers = store.list_officers()
    shifts = store.list_shifts()
    assignments = store.get_week_assignments(monday)

    if not officers or not shifts:
        st.info("Add officers and shift codes first.")
        return

    code_to_shift = {s.code: s for s in shifts}
    name_by_ic = {o.ic_number: o.name for o in officers}

    # Pick which day to rebalance.
    day = st.selectbox("Day", week_dates(monday), format_func=lambda d: d.strftime("%a %d %b"))

    # Build buckets: shift_code -> [name, ...], plus an "Unassigned" bucket.
    buckets: dict[str, list[str]] = {"(unassigned)": []}
    for s in shifts:
        buckets.setdefault(s.code, [])
    by_ic = {a.ic_number: a for a in assignments if a.on_date == day}
    for o in officers:
        if o.ic_number in by_ic:
            buckets.setdefault(by_ic[o.ic_number].shift_code, []).append(o.name)
        else:
            buckets["(unassigned)"].append(o.name)

    items = [{"header": code, "items": buckets[code]} for code in buckets]
    sorted_items = sort_items(items, multi_containers=True, direction="vertical")

    # Diff: who moved from where to where?
    name_to_ic = {v: k for k, v in name_by_ic.items()}
    moves = 0
    for container in sorted_items:
        new_code = container["header"]
        for name in container["items"]:
            ic = name_to_ic.get(name)
            if not ic:
                continue
            current = by_ic.get(ic)
            current_code = current.shift_code if current else "(unassigned)"
            if new_code != current_code:
                store.set_assignment(
                    ic_number=ic,
                    on_date=day,
                    shift_code=None if new_code == "(unassigned)" else new_code,
                    actor_email=user.email,
                )
                moves += 1
    if moves:
        st.toast(f"Saved {moves} reassignment(s).", icon="✅")
        st.cache_data.clear()
        st.rerun()

    with st.expander("Color legend"):
        cols = st.columns(4)
        for i, (k, v) in enumerate(DUTY_COLORS.items()):
            with cols[i % 4]:
                st.markdown(
                    f"<span style='display:inline-block;width:12px;height:12px;"
                    f"background:{v};border-radius:2px;margin-right:6px;'></span>{k}",
                    unsafe_allow_html=True,
                )


main()
