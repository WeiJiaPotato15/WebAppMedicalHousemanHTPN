"""Admin: kanban-by-day drag-and-drop view (secondary editor).

Officers are bucketed by **individual shift code** (EH W1, EH W2, MOPD OH W3,
…), not by duty type. Each column header is the exact shift code, so dropping
an officer into a column writes that code directly — no auto-resolution. An
"(unassigned)" column holds officers with no shift on the selected day.

For free-text edits use Edit Roster.
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

# Visual ordering of the duty-type *groups* the columns are sorted by.
# Anything not listed falls to the end alphabetically by duty_type.
DUTY_TYPE_ORDER = [
    "EH", "OH", "OC", "TAG",
    "MOPD", "PERI", "PENDING ED",
    "AL", "MC/EL", "OFF", "PC", "COURSE", "EOP",
]


def main() -> None:
    user = require_admin()
    st_autorefresh(interval=5_000, key="kanban_refresh")
    beat(user.email, user.name, PAGE_NAME)
    render_sidebar(user.email)

    st.title("🎯 Kanban view")
    st.caption(
        "Drag an officer chip into a shift-code column to assign that exact "
        "code. Columns are grouped by duty type (EH, OH, …). For free-text "
        "edits use Edit Roster."
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

    shift_by_code = {s.code: s for s in shifts}
    name_by_ic = {o.ic_number: o.name for o in officers}

    # Pick which day to rebalance.
    day = st.selectbox("Day", week_dates(monday), format_func=lambda d: d.strftime("%a %d %b"))

    # Build buckets keyed by shift_code (one per known code) plus "(unassigned)".
    UNASSIGNED = "(unassigned)"
    buckets: dict[str, list[str]] = {UNASSIGNED: []}
    for s in shifts:
        buckets[s.code] = []

    by_ic = {a.ic_number: a for a in assignments if a.on_date == day}
    for o in officers:
        a = by_ic.get(o.ic_number)
        if a and a.shift_code in buckets:
            buckets[a.shift_code].append(o.name)
        elif a:
            # Officer is assigned a code that's no longer in the master shift
            # list — surface it as its own column so admins can move them out.
            buckets.setdefault(a.shift_code, []).append(o.name)
        else:
            buckets[UNASSIGNED].append(o.name)

    # Order columns: unassigned first, then by duty_type group, then by code.
    duty_rank = {dt: i for i, dt in enumerate(DUTY_TYPE_ORDER)}

    def col_key(code: str) -> tuple:
        if code == UNASSIGNED:
            return (-1, "", "")
        s = shift_by_code.get(code)
        if s is None:
            return (len(DUTY_TYPE_ORDER) + 1, "", code)
        rank = duty_rank.get(s.duty_type, len(DUTY_TYPE_ORDER))
        return (rank, s.duty_type, code)

    ordered_codes = sorted(buckets.keys(), key=col_key)
    items = [{"header": k, "items": buckets[k]} for k in ordered_codes]

    sorted_items = sort_items(items, multi_containers=True, direction="vertical")

    # Diff: who moved between shift codes?
    name_to_ic = {v: k for k, v in name_by_ic.items()}
    moves = 0
    for container in sorted_items:
        new_label = container["header"]
        new_code = None if new_label == UNASSIGNED else new_label
        for name in container["items"]:
            ic = name_to_ic.get(name)
            if not ic:
                continue
            current = by_ic.get(ic)
            current_code = current.shift_code if current else None
            if new_code == current_code:
                continue  # no change
            store.set_assignment(
                ic_number=ic,
                on_date=day,
                shift_code=new_code,
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
