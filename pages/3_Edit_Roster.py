"""Admin: edit the roster as a spreadsheet grid.

Rows = officers (filtered to those whose posting has started by week's end and
whose EOP, if any, is not before week's start). Columns = days. Each cell is
a dropdown populated from the master shift list. Writes to cells after a
freshly-set EOP are rejected with a toast — once an HO is marked end-of-posting
on day D, days D+1…D+6 cannot be assigned.

Auto-refresh every 5s pulls in other admins' changes; presence sidebar shows
who else is editing.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from lib.auth import require_admin
from lib.constants import (
    CRITICAL_COVERAGE_CATEGORIES,
    DUTY_COLORS,
    WEEKEND_OK_CATEGORIES,
    safe_secret,
    week_dates,
    week_label,
    week_start,
)
from lib.db import get_store
from lib.presence import beat, render_sidebar
from lib.viz import (
    HOURS_HIGH,
    HOURS_LOW,
    assignments_df,
    daily_category_counts,
    hours_per_staff_figure,
    staff_per_station_per_day_figure,
)

st.set_page_config(page_title="Edit Roster — HTPN", page_icon="📝", layout="wide")
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
    week_sunday = monday + timedelta(days=6)
    clabel.subheader(f"Week of {week_label(monday)}")

    store = get_store()
    all_officers = store.list_officers()
    shifts = store.list_shifts()
    assignments = store.get_week_assignments(monday)
    template_ics = store.get_week_template(monday)
    eop_dates = store.list_eop_dates()
    eop_codes = {s.code for s in shifts if s.duty_type == "EOP"}

    if not all_officers:
        st.warning("Add house officers first on the **Officers** page.")
        return
    if not shifts:
        st.warning("Add shift codes first on the **Master Data** page.")
        return

    # Row order: template if this week was explicitly created, else group by
    # ward then alphabetical name.
    by_ic = {o.ic_number: o for o in all_officers}
    if template_ics:
        ordered = [by_ic[ic] for ic in template_ics if ic in by_ic]
        st.caption(
            f"Roster created with {len(ordered)} officers in fixed order. "
            "Adding/removing officers globally won't affect this week's row layout."
        )
    else:
        ordered = sorted(all_officers, key=lambda x: ((x.ward_group or "~"), x.name))

    # Apply posting-window filter: hide HOs whose posting hasn't started by
    # week's end, and HOs whose EOP fell before this week's Monday.
    def in_window(o) -> bool:
        if o.posting_start_date > week_sunday:
            return False  # not yet posting
        eop = eop_dates.get(o.ic_number)
        if eop is not None and eop < monday:
            return False  # already finished
        return True

    officers = [o for o in ordered if in_window(o)]
    excluded = len(ordered) - len(officers)
    if excluded:
        st.caption(
            f"_{excluded} HO(s) hidden — posting hasn't started yet, or EOP was before this week._"
        )

    if not officers:
        st.info("No house officers active in this week.")
        return

    days = week_dates(monday)
    day_cols = [d.strftime("%a %d/%m") for d in days]
    shifts_by_code = {s.code: s for s in shifts}

    # Build the grid as a DataFrame: ward + name + (hidden) ic_number, then days.
    by_key = {(a.ic_number, a.on_date): a for a in assignments}
    grid_rows = []
    for o in officers:
        row = {
            "ward": o.ward_group or "—",
            "name": o.name,
            "ic_number": o.ic_number,
        }
        for d, dlabel in zip(days, day_cols):
            row[dlabel] = by_key[(o.ic_number, d)].shift_code if (o.ic_number, d) in by_key else ""
        grid_rows.append(row)
    grid = pd.DataFrame(grid_rows)

    shift_options = [""] + [s.code for s in shifts]
    column_config: dict = {
        "ward": st.column_config.TextColumn("Ward", disabled=True, width="small"),
        "name": st.column_config.TextColumn("Name", disabled=True),
        "ic_number": st.column_config.TextColumn("IC", disabled=True),
    }
    for c in day_cols:
        column_config[c] = st.column_config.SelectboxColumn(c, options=shift_options, required=False)

    edited = st.data_editor(
        grid,
        column_config=column_config,
        column_order=("ward", "name", *day_cols),  # hide ic_number column from view
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=f"editor_{monday.isoformat()}",
    )

    # Compute effective EOP per officer for the post-save validation:
    # min(saved EOP outside this week, EOP in the edited state for this week).
    external_eop: dict[str, date] = {
        ic: d for ic, d in eop_dates.items() if d < monday or d > week_sunday
    }
    in_week_eop: dict[str, date] = {}
    for _, r in edited.iterrows():
        ic = r["ic_number"]
        for d, dlabel in zip(days, day_cols):
            code = r[dlabel]
            if code in eop_codes:
                cur = in_week_eop.get(ic)
                if cur is None or d < cur:
                    in_week_eop[ic] = d

    def effective_eop(ic: str) -> date | None:
        cands = []
        if ic in external_eop:
            cands.append(external_eop[ic])
        if ic in in_week_eop:
            cands.append(in_week_eop[ic])
        return min(cands) if cands else None

    # Diff and persist
    if not edited.equals(grid):
        saved = 0
        blocked_pre: list[str] = []
        blocked_post: list[str] = []
        for i, row in edited.iterrows():
            ic = row["ic_number"]
            name = row["name"]
            posting_start = by_ic[ic].posting_start_date if ic in by_ic else None
            eop = effective_eop(ic)
            for d, dlabel in zip(days, day_cols):
                new = (row[dlabel] or "") if pd.notna(row[dlabel]) else ""
                old = grid.at[i, dlabel] if dlabel in grid.columns else ""
                if new == old:
                    continue
                # Reject non-empty writes to cells before the HO's posting starts
                if new and posting_start is not None and d < posting_start:
                    blocked_pre.append(f"{name} on {d.strftime('%a %d/%m')} ({new})")
                    continue
                # Reject non-empty writes to cells strictly after the effective EOP
                if new and eop is not None and d > eop:
                    blocked_post.append(f"{name} on {d.strftime('%a %d/%m')} ({new})")
                    continue
                store.set_assignment(
                    ic_number=ic,
                    on_date=d,
                    shift_code=(new or None),
                    actor_email=user.email,
                )
                saved += 1
        if saved:
            st.toast(f"Saved {saved} change(s).", icon="✅")
        if blocked_pre:
            st.warning(
                f"Blocked {len(blocked_pre)} write(s) before posting start — that HO "
                f"hasn't joined yet. Rejected: "
                + "; ".join(blocked_pre[:5])
                + (f"; +{len(blocked_pre)-5} more" if len(blocked_pre) > 5 else "")
            )
        if blocked_post:
            st.warning(
                f"Blocked {len(blocked_post)} write(s) to cells after EOP — once an HO "
                f"is marked end-of-posting, later days are locked. Rejected: "
                + "; ".join(blocked_post[:5])
                + (f"; +{len(blocked_post)-5} more" if len(blocked_post) > 5 else "")
            )
        st.cache_data.clear()
        st.rerun()

    # ---- Duty-type colour legend (same as the public Overview) ------------ #
    with st.expander("Legend (duty types)"):
        cols = st.columns(4)
        for i, (k, v) in enumerate(DUTY_COLORS.items()):
            with cols[i % 4]:
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;background:{v};"
                    f"border-radius:3px;margin-right:6px;'></span>{k}",
                    unsafe_allow_html=True,
                )

    # ---- Hours summary with under-/over-band highlighting ------------------ #
    summary_rows = []
    for _, r in edited.iterrows():
        filled = sum(1 for c in day_cols if r[c])
        total = sum(
            shifts_by_code[r[c]].hours
            for c in day_cols
            if r[c] and r[c] in shifts_by_code
        )
        summary_rows.append({
            "Ward": r.get("ward", "—"),
            "Name": r["name"],
            "Hours": int(total),
            "_filled": filled,
        })
    summary = pd.DataFrame(summary_rows)

    over = summary[summary["Hours"] > HOURS_HIGH]
    under = summary[(summary["Hours"] < HOURS_LOW) & (summary["_filled"] > 0)]

    if not over.empty:
        st.error(
            f"⚠️ **{len(over)} HO(s) over the {HOURS_HIGH}h cap**: "
            + ", ".join(f"{n} ({h}h)" for n, h in zip(over["Name"], over["Hours"]))
        )
    if not under.empty:
        st.warning(
            f"⚠️ {len(under)} HO(s) under the {HOURS_LOW}h target: "
            + ", ".join(f"{n} ({h}h)" for n, h in zip(under["Name"], under["Hours"]))
        )

    st.caption(
        f"**Hours summary** — yellow = under {HOURS_LOW}h (too few), "
        f"red = over {HOURS_HIGH}h. {HOURS_LOW}-{HOURS_HIGH}h is the accepted band."
    )

    def _highlight(row):
        h = row["Hours"]
        if h > HOURS_HIGH:
            return ["background-color: #fee2e2; color: #991b1b; font-weight: 600"] * len(row)
        if h < HOURS_LOW and row["_filled"] > 0:
            return ["background-color: #fef3c7; color: #92400e"] * len(row)
        return [""] * len(row)

    st.dataframe(
        summary.style.apply(_highlight, axis=1),
        hide_index=True,
        column_order=("Ward", "Name", "Hours"),
        width="stretch",
    )

    # ---- Staff per category per day ---------------------------------------- #
    st.subheader("Staff per category per day")
    st.caption(
        "Counts based on the grid above. Wards count people physically in W1/W2/… "
        "(EH/OH/OC/TAG). MOPD, PERI, MC/EL, OFF etc. count by duty type."
    )
    cat_table = daily_category_counts(edited, day_cols, days, shifts_by_code)
    if cat_table.empty:
        st.info("No assignments yet to summarize.")
    else:
        def _highlight_critical_zeros(row):
            cat = row.name
            if cat not in CRITICAL_COVERAGE_CATEGORIES:
                return [""] * len(row)
            out = []
            for col, val in row.items():
                is_zero = isinstance(val, (int, float)) and val == 0
                if not is_zero:
                    out.append("")
                    continue
                # Per-category weekend exemption (e.g. MOPD doesn't run weekends).
                is_weekend = isinstance(col, str) and (
                    col.startswith("Sat") or col.startswith("Sun")
                )
                if is_weekend and cat in WEEKEND_OK_CATEGORIES:
                    out.append("")
                    continue
                out.append("background-color: #fee2e2; color: #991b1b")
            return out

        st.dataframe(
            cat_table.style.apply(_highlight_critical_zeros, axis=1),
            width="stretch",
        )

    # ---- Create roster for next week --------------------------------------- #
    next_monday = monday + timedelta(days=7)
    current_has_data = bool(assignments) or template_ics is not None
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
            # Drop officers whose End-of-Posting is before next Monday — they've
            # already finished their rotation, so don't carry them forward.
            carried = [
                o.ic_number for o in officers
                if (eop_dates.get(o.ic_number) is None) or (eop_dates[o.ic_number] >= next_monday)
            ]
            dropped = len(officers) - len(carried)
            store.create_week_template(
                monday=next_monday,
                officer_ic_numbers=carried,
                actor_email=user.email,
            )
            st.session_state.edit_monday = next_monday
            st.cache_data.clear()
            msg = f"Started next week ({week_label(next_monday)})."
            if dropped:
                msg += f" Dropped {dropped} HO(s) past EOP."
            st.toast(msg, icon="🆕")
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
