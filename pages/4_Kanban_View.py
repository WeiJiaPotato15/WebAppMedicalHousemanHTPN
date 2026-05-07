"""Admin: kanban-by-day drag-and-drop view (secondary editor).

Officers are grouped by **duty type** (EH, OH, OC, MOPD, PERI, OFF, …) rather
than by individual shift code, so the column count stays manageable. When an
admin drags an officer between duty-type columns, the page auto-resolves the
specific shift code based on the officer's ward_group:

- single-code duty types (OFF, PC, AL, MC/EL, COURSE, EOP) → the lone code
- ward-attached (EH, OH, TAG) → match the officer's ward_group
- MOPD / PERI / PENDING ED with multiple variants → prefer OH (office hours)
- OC and unmatched cases → first available shift code, alphabetically

For exact code-level edits, use the Edit Roster page.
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

# Visual ordering of duty-type columns. Anything not listed here falls to the
# end alphabetically.
DUTY_TYPE_ORDER = [
    "(unassigned)",
    "EH", "OH", "OC", "TAG",
    "MOPD", "PERI", "PENDING ED",
    "AL", "MC/EL", "OFF", "PC", "COURSE", "EOP",
]


def _resolve_shift_code(duty_type: str, officer, candidates: list) -> str | None:
    """Pick a single shift code for (duty_type, officer)."""
    if duty_type == "(unassigned)" or not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].code
    # Prefer codes whose ward matches the officer's ward_group
    if officer.ward_group:
        ward_match = [c for c in candidates if c.ward == officer.ward_group]
        if ward_match:
            # Within a ward (e.g. MOPD W1 has EH and OH variants), prefer OH
            oh_first = [c for c in ward_match if " OH " in f" {c.code} " or c.code.endswith("OH")]
            return (oh_first or ward_match)[0].code
    # No ward match: prefer OH variant overall, else alphabetical first
    oh_first = [c for c in candidates if " OH " in f" {c.code} " or c.code.endswith("OH")]
    return (oh_first or candidates)[0].code


def main() -> None:
    user = require_admin()
    st_autorefresh(interval=5_000, key="kanban_refresh")
    beat(user.email, user.name, PAGE_NAME)
    render_sidebar(user.email)

    st.title("🎯 Kanban view")
    st.caption(
        "Visual rebalance of the week, grouped by duty type. Drag officer chips "
        "between columns; the specific shift code is auto-picked from the "
        "officer's ward group. For free-text edits use Edit Roster."
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

    code_to_duty = {s.code: s.duty_type for s in shifts}
    by_duty: dict[str, list] = {}
    for s in shifts:
        by_duty.setdefault(s.duty_type, []).append(s)

    name_by_ic = {o.ic_number: o.name for o in officers}
    officer_by_ic = {o.ic_number: o for o in officers}

    # Pick which day to rebalance.
    day = st.selectbox("Day", week_dates(monday), format_func=lambda d: d.strftime("%a %d %b"))

    # Build buckets keyed by duty_type.
    buckets: dict[str, list[str]] = {"(unassigned)": []}
    for dt in by_duty:
        buckets[dt] = []
    by_ic = {a.ic_number: a for a in assignments if a.on_date == day}
    for o in officers:
        if o.ic_number in by_ic:
            dt = code_to_duty.get(by_ic[o.ic_number].shift_code, "?")
            buckets.setdefault(dt, []).append(o.name)
        else:
            buckets["(unassigned)"].append(o.name)

    # Order columns: known list first, then any unknown duty types alphabetical.
    ordered_keys = [k for k in DUTY_TYPE_ORDER if k in buckets]
    extras = sorted(k for k in buckets if k not in DUTY_TYPE_ORDER)
    items = [{"header": k, "items": buckets[k]} for k in ordered_keys + extras]

    sorted_items = sort_items(items, multi_containers=True, direction="vertical")

    # Diff: who moved between duty types?
    name_to_ic = {v: k for k, v in name_by_ic.items()}
    moves = 0
    for container in sorted_items:
        new_duty = container["header"]
        for name in container["items"]:
            ic = name_to_ic.get(name)
            if not ic:
                continue
            current = by_ic.get(ic)
            current_duty = code_to_duty.get(current.shift_code, "?") if current else "(unassigned)"
            if new_duty == current_duty:
                continue  # no change
            officer = officer_by_ic.get(ic)
            new_code = _resolve_shift_code(new_duty, officer, by_duty.get(new_duty, []))
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
