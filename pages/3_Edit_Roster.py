"""Admin: edit the roster as a spreadsheet grid.

Rows = officers. Columns = days of the chosen week. Each cell is a dropdown
populated from the master shift list. Auto-refresh every 5s pulls in other
admins' changes; presence sidebar shows who else is editing.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from lib.auth import require_admin
from lib.constants import safe_secret, week_dates, week_label, week_start
from lib.db import get_store
from lib.presence import beat, render_sidebar
from lib.viz import (
    assignments_df,
    hours_per_staff_figure,
    staff_per_station_per_day_figure,
)

st.set_page_config(page_title="Edit Roster — HKJ", page_icon="📝", layout="wide")
PAGE_NAME = "Edit Roster"


def main() -> None:
    user = require_admin()
    st_autorefresh(interval=5_000, key="edit_roster_refresh")
    beat(user.email, user.name, PAGE_NAME)
    render_sidebar(user.email)

    st.title("📝 Edit Roster")
    st.caption(f"Signed in as {user.name} ({user.email}). Changes save instantly. "
               "All edits are logged in the Activity page.")

    if "edit_monday" not in st.session_state:
        st.session_state.edit_monday = week_start(date.today())

    cprev, clabel, cnext, ctoday = st.columns([1, 5, 1, 1])
    if cprev.button("◀ Prev"):
        st.session_state.edit_monday -= timedelta(days=7)
    if cnext.button("Next ▶"):
        st.session_state.edit_monday += timedelta(days=7)
    if ctoday.button("This week"):
        st.session_state.edit_monday = week_start(date.today())
    monday = st.session_state.edit_monday
    clabel.subheader(f"Week of {week_label(monday)}")

    store = get_store()
    all_officers = store.list_officers()
    shifts = store.list_shifts()
    assignments = store.get_week_assignments(monday)
    template_emails = store.get_week_template(monday)

    if not all_officers:
        st.warning("Add house officers first on the **Officers** page.")
        return
    if not shifts:
        st.warning("Add shift codes first on the **Master Data** page.")
        return

    # Row order: template if this week was explicitly created, else global officer list.
    # Filter to officers that still exist (deleted ones are dropped, not preserved as ghosts).
    by_email = {o.email: o for o in all_officers}
    if template_emails:
        officers = [by_email[e] for e in template_emails if e in by_email]
        st.caption(
            f"Roster created with {len(officers)} officers in fixed order. "
            "Adding/removing officers globally won't affect this week's row layout."
        )
    else:
        officers = all_officers

    days = week_dates(monday)
    day_cols = [d.strftime("%a %d/%m") for d in days]

    # Build the grid as a DataFrame: index by officer name, columns by date.
    by_key = {(a.email, a.on_date): a for a in assignments}
    grid_rows = []
    for o in officers:
        row = {"name": o.name, "email": o.email}
        for d, dlabel in zip(days, day_cols):
            row[dlabel] = by_key[(o.email, d)].shift_code if (o.email, d) in by_key else ""
        grid_rows.append(row)
    grid = pd.DataFrame(grid_rows)

    shift_options = [""] + [s.code for s in shifts]
    column_config: dict = {
        "name": st.column_config.TextColumn("Name", disabled=True),
        "email": st.column_config.TextColumn("Email", disabled=True),
    }
    for c in day_cols:
        column_config[c] = st.column_config.SelectboxColumn(c, options=shift_options, required=False)

    edited = st.data_editor(
        grid,
        column_config=column_config,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=f"editor_{monday.isoformat()}",
    )

    # Diff and persist
    if not edited.equals(grid):
        n = 0
        for i, row in edited.iterrows():
            email = row["email"]
            for d, dlabel in zip(days, day_cols):
                new = (row[dlabel] or "") if pd.notna(row[dlabel]) else ""
                old = grid.at[i, dlabel] if dlabel in grid.columns else ""
                if new == old:
                    continue
                store.set_assignment(
                    email=email,
                    on_date=d,
                    shift_code=(new or None),
                    actor_email=user.email,
                )
                n += 1
        st.toast(f"Saved {n} change(s).", icon="✅")
        # Bust caches so other admins / the public page pick this up immediately.
        st.cache_data.clear()
        st.rerun()

    # ---- Create roster for next week --------------------------------------- #
    next_monday = monday + timedelta(days=7)
    current_has_data = bool(assignments) or template_emails is not None
    next_has_data = store.has_week_data(next_monday)
    if current_has_data and not next_has_data:
        st.divider()
        st.markdown("##### Plan ahead")
        c1, c2 = st.columns([3, 2])
        c1.caption(
            f"Carry the same {len(officers)} officers (in this exact row order) "
            f"into the week of **{week_label(next_monday)}**, with all shift cells blank."
        )
        if c2.button("➕ Create roster for next week", type="primary",
                     key=f"create_next_{next_monday.isoformat()}"):
            store.create_week_template(
                monday=next_monday,
                officer_emails=[o.email for o in officers],
                actor_email=user.email,
            )
            st.session_state.edit_monday = next_monday
            st.cache_data.clear()
            st.toast(f"Started next week ({week_label(next_monday)}). Switched to it.", icon="🆕")
            st.rerun()
    elif current_has_data and next_has_data:
        st.caption(f"Next week ({week_label(next_monday)}) is already started — use **Next ▶** to view.")

    st.divider()
    st.subheader("Coverage & hours preview")
    df = assignments_df(assignments, shifts, officers)
    min_per_ward = int(safe_secret("app", "default_min_staff_per_ward", 1))
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            staff_per_station_per_day_figure(df, min_per_ward),
            width="stretch", config={"displayModeBar": False},
        )
    with c2:
        st.plotly_chart(
            hours_per_staff_figure(df),
            width="stretch", config={"displayModeBar": False},
        )


main()
