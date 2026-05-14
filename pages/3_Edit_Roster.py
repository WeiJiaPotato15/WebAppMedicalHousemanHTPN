"""Admin: edit the roster as a spreadsheet grid.

Rows = officers (filtered to those whose posting has started by week's end and
whose EOP, if any, is not before week's start). Columns = days. Each cell is
a dropdown populated from the master shift list.

Workflow is **Edit → Save**:
- Edits stay local in the data_editor; the panels below (heatmap, hours
  summary, per-category counts) re-render off the live editor state.
- 💾 Save persists the diff. Writes to cells before posting start or after a
  set EOP are rejected and the rejection alert is stashed in session state so
  it survives the post-save rerun. The alert auto-dismisses as soon as the
  admin starts editing again.

Editing is single-admin by policy — no autorefresh; presence sidebar shows
anyone who happens to be on the page.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import (
    CRITICAL_COVERAGE_CATEGORIES,
    DUTY_COLORS,
    LEAVE_CAP_DEFAULT,
    POSTPONEMENT_DAYS_PER_BUMP,
    WEEKEND_OK_CATEGORIES,
    compute_tentative_eop,
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
    week_grid_figure,
)

st.set_page_config(page_title="Edit Roster — HTPN", page_icon="📝", layout="wide")
PAGE_NAME = "Edit Roster"


def main() -> None:
    user = require_admin()
    beat(user.email, user.name, PAGE_NAME)
    render_sidebar(user.email)

    st.title("📝 Edit Roster")
    st.caption(
        f"Signed in as {user.name} ({user.email}). "
        "Edit cells in the grid, then click **💾 Save changes** to persist. "
        "All saves are logged in the Activity page."
    )

    # Editor version: bumped after every save so data_editor reloads from the
    # fresh DB state. Without this, rejected edits stay visible in the editor
    # and a repeat save would re-trigger the same warning.
    st.session_state.setdefault("edit_roster_version", 0)
    # Last save's saved-count + blocked lists, kept across the post-save rerun
    # so the admin actually sees them (st.rerun() otherwise wipes mid-run UI).
    # Cleared automatically once the admin starts editing again.
    st.session_state.setdefault("edit_roster_last_save", None)

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
    is_published = get_store().is_week_published(monday)
    badge = "" if is_published else "  📝 DRAFT — not visible to public"
    clabel.subheader(f"Week of {week_label(monday)}{badge}")

    store = get_store()
    all_officers = store.list_officers()
    shifts = store.list_shifts()
    assignments = store.get_week_assignments(monday)
    template_ics = store.get_week_template(monday)
    eop_dates = store.list_eop_dates()             # effective EOP (cell or tentative)
    eop_cell_dates = store.list_eop_cell_dates()   # only real EOP cells (overrides)
    leave_counts = store.list_leave_counts()
    leave_cap = int(safe_secret("app", "leave_cap", LEAVE_CAP_DEFAULT))
    eop_codes = {s.code for s in shifts if s.duty_type == "EOP"}

    if not all_officers:
        st.warning("Add house officers first on the **Officers** page.")
        return
    if not shifts:
        st.warning("Add shift codes first on the **Master Data** page.")
        return

    # Render-time sweep: clear any saved cells outside [posting_start, real_eop_cell]
    # for officers in this week. Only sweeps past a *real* EOP cell — tentative
    # EOP doesn't trigger sweeping (the postponement bump handles that).
    by_ic_full = {o.ic_number: o for o in all_officers}
    swept = []
    kept_assignments = []
    for a in assignments:
        o = by_ic_full.get(a.ic_number)
        if o is None:
            kept_assignments.append(a)
            continue
        if a.on_date < o.posting_start_date:
            store.set_assignment(a.ic_number, a.on_date, None, user.email)
            swept.append((o.name, a.on_date, a.shift_code, "before posting"))
            continue
        eop = eop_cell_dates.get(a.ic_number)
        if eop is not None and a.on_date > eop:
            store.set_assignment(a.ic_number, a.on_date, None, user.email)
            swept.append((o.name, a.on_date, a.shift_code, "after EOP"))
            continue
        kept_assignments.append(a)
    assignments = kept_assignments
    if swept:
        st.info(
            f"Auto-cleared {len(swept)} stale cell(s) outside posting window: "
            + "; ".join(f"{n} on {d.strftime('%a %d/%m')} ({c}, {r})" for n, d, c, r in swept[:5])
            + (f"; +{len(swept)-5} more" if len(swept) > 5 else "")
        )

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
    # week's end, and HOs whose *real* EOP cell is before this week's Monday.
    # Tentative EOP is informational only — admins can keep scheduling past it
    # (the postponement bumps if they replace the tentative cell when it shows
    # up in a visible week).
    def in_window(o) -> bool:
        if o.posting_start_date > week_sunday:
            return False  # not yet posting
        cell_eop = eop_cell_dates.get(o.ic_number)
        if cell_eop is not None and cell_eop < monday:
            return False  # marked done by a real EOP cell
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

    # Tentative EOP overlay: for each officer in view who has NO real EOP cell,
    # if their tentative EOP falls in this week and the cell is empty, prefill
    # the grid with "EOP" as a visual hint. Stored separately as overlay_cells
    # so the save loop can distinguish them from real writes.
    tentative_eops: dict[str, date] = {}
    for o in officers:
        tentative_eops[o.ic_number] = compute_tentative_eop(
            posting_start=o.posting_start_date,
            mc_count=leave_counts.get(o.ic_number, 0),
            postponement_count=o.postponement_count,
            leave_cap=leave_cap,
        )
    overlay_cells: set[tuple[str, date]] = set()
    display_grid = grid.copy()
    for o in officers:
        if o.ic_number in eop_cell_dates:
            continue  # has a real EOP cell — no overlay
        teop = tentative_eops[o.ic_number]
        if not (monday <= teop <= week_sunday):
            continue
        if (o.ic_number, teop) in by_key:
            continue  # cell is already occupied by a real assignment
        dlabel = teop.strftime("%a %d/%m")
        idx = display_grid.index[display_grid["ic_number"] == o.ic_number]
        if len(idx) and dlabel in display_grid.columns:
            display_grid.at[idx[0], dlabel] = "EOP"
            overlay_cells.add((o.ic_number, teop))

    if overlay_cells:
        names_by_ic = {o.ic_number: o.name for o in officers}
        notes = ", ".join(
            f"{names_by_ic.get(ic, ic)} ({d.strftime('%a %d/%m')})"
            for ic, d in sorted(overlay_cells, key=lambda x: x[1])
        )
        st.caption(
            f"💡 Tentative EOP this week — {notes}. "
            f"These cells display **EOP** automatically. Replace with another shift "
            f"to postpone EOP by {POSTPONEMENT_DAYS_PER_BUMP} days; place an EOP cell "
            "elsewhere to override the date entirely."
        )

    shift_options = [""] + [s.code for s in shifts]
    column_config: dict = {
        "ward": st.column_config.TextColumn("Ward", disabled=True, width="small"),
        "name": st.column_config.TextColumn("Name", disabled=True),
        "ic_number": st.column_config.TextColumn("IC", disabled=True),
    }
    for c in day_cols:
        column_config[c] = st.column_config.SelectboxColumn(c, options=shift_options, required=False)

    # ---- Auto-dismiss stale save alerts ----------------------------------- #
    # If the admin has touched a cell since the last save, drop the alert from
    # that save. Detects pending edits via the data_editor's session_state
    # (Streamlit stores `edited_rows` under the widget's key). Without this,
    # the alert from a previous save would linger on screen forever.
    ver = st.session_state.edit_roster_version
    editor_key = f"editor_{monday.isoformat()}_{ver}"
    prior_editor_state = st.session_state.get(editor_key, {})
    has_resumed_editing = (
        bool(prior_editor_state.get("edited_rows"))
        or bool(prior_editor_state.get("added_rows"))
        or bool(prior_editor_state.get("deleted_rows"))
    )
    if has_resumed_editing and st.session_state.edit_roster_last_save is not None:
        st.session_state.edit_roster_last_save = None

    # ---- Persisted alerts from the previous Save click -------------------- #
    # Rendered BEFORE the editor so they're impossible to miss. They stay
    # visible until either: (a) the admin starts editing again (auto-clear
    # above), or (b) another save click overwrites them.
    last_save = st.session_state.edit_roster_last_save
    if last_save is not None:
        if last_save.get("saved"):
            st.success(f"✅ Saved {last_save['saved']} change(s) on the last save.")
        if last_save.get("blocked_pre"):
            entries = last_save["blocked_pre"]
            st.error(
                f"🚫 **{len(entries)} write(s) blocked — before posting start.** "
                "These house officers haven't joined yet on those dates: "
                + "; ".join(entries[:8])
                + (f"; +{len(entries) - 8} more" if len(entries) > 8 else "")
            )
        if last_save.get("blocked_post"):
            entries = last_save["blocked_post"]
            st.error(
                f"🚫 **{len(entries)} write(s) blocked — after EOP.** "
                "Once an HO is marked end-of-posting, later days are locked: "
                + "; ".join(entries[:8])
                + (f"; +{len(entries) - 8} more" if len(entries) > 8 else "")
            )
        if last_save.get("bumped"):
            entries = last_save["bumped"]
            st.info(
                f"⏩ **EOP postponed +{POSTPONEMENT_DAYS_PER_BUMP}d for {len(entries)} HO(s)**: "
                + "; ".join(entries[:8])
                + (f"; +{len(entries) - 8} more" if len(entries) > 8 else "")
            )

    edited = st.data_editor(
        display_grid,
        column_config=column_config,
        column_order=("ward", "name", *day_cols),  # hide ic_number column from view
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=editor_key,
    )

    # Compute effective EOP per officer for the post-save validation.
    # Real EOP cells (saved in other weeks OR newly placed in the edited state)
    # win; otherwise fall back to the tentative formula. An overlay cell still
    # showing "EOP" doesn't count as a real cell write — admin would need to
    # actively place an EOP cell on a different date for it to override.
    external_cell_eop: dict[str, date] = {
        ic: d for ic, d in eop_cell_dates.items() if d < monday or d > week_sunday
    }
    in_week_cell_eop: dict[str, date] = {}
    for _, r in edited.iterrows():
        ic = r["ic_number"]
        for d, dlabel in zip(days, day_cols):
            code = r[dlabel]
            if code in eop_codes and (ic, d) not in overlay_cells:
                cur = in_week_cell_eop.get(ic)
                if cur is None or d < cur:
                    in_week_cell_eop[ic] = d

    def effective_eop(ic: str) -> date | None:
        # Only real EOP cells block writes. Tentative EOP is informational —
        # admins can keep scheduling past it; the postponement bumps when
        # admin replaces an overlay cell that's actually shown in the week.
        cands = []
        if ic in external_cell_eop:
            cands.append(external_cell_eop[ic])
        if ic in in_week_cell_eop:
            cands.append(in_week_cell_eop[ic])
        return min(cands) if cands else None

    # ---- Save bar --------------------------------------------------------- #
    has_changes = not edited.equals(display_grid)
    save_col, hint_col = st.columns([1, 5])
    save_clicked = save_col.button(
        "💾 Save changes",
        type="primary",
        disabled=not has_changes,
        key=f"save_{monday.isoformat()}_{ver}",
    )
    if has_changes and not save_clicked:
        hint_col.caption("⚠ Unsaved changes — click **💾 Save changes** to persist.")

    if save_clicked:
        saved = 0
        blocked_pre: list[str] = []
        blocked_post: list[str] = []
        # Track whether each officer ends this save with any real EOP cell:
        # used after the write loop to decide whether overlay-cell overwrites
        # should bump postponement_count.
        has_real_cell_after: dict[str, bool] = {}
        for ic in {r["ic_number"] for _, r in edited.iterrows()}:
            has_real_cell_after[ic] = ic in eop_cell_dates  # external real cell
        for i, row in edited.iterrows():
            ic = row["ic_number"]
            name = row["name"]
            posting_start = by_ic[ic].posting_start_date if ic in by_ic else None
            eop = effective_eop(ic)
            for d, dlabel in zip(days, day_cols):
                new = (row[dlabel] or "") if pd.notna(row[dlabel]) else ""
                is_overlay = (ic, d) in overlay_cells
                # For overlay cells the "real" old value is empty, not "EOP" —
                # so an admin keeping the overlay as EOP is a no-op write, and
                # admin actively replacing it shows a true diff vs the DB.
                old = "" if is_overlay else (grid.at[i, dlabel] if dlabel in grid.columns else "")
                # Special case: keeping the tentative as EOP doesn't materialize
                # it as a real cell. Stays tentative (auto-tracks MC accrual).
                if is_overlay and new in eop_codes:
                    continue
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
                if new in eop_codes:
                    has_real_cell_after[ic] = True

        # Postponement detection: for each overlay cell, if admin saved a
        # non-empty non-EOP shift AND the officer doesn't end up with a real
        # EOP cell elsewhere, bump postponement_count by 1 (= +14 days).
        bumped_msgs: list[str] = []
        for ic, d in overlay_cells:
            row_match = edited[edited["ic_number"] == ic]
            if row_match.empty:
                continue
            dlabel = d.strftime("%a %d/%m")
            new_val = row_match[dlabel].iloc[0] if dlabel in row_match.columns else ""
            new_val = (new_val or "") if pd.notna(new_val) else ""
            if not new_val or new_val in eop_codes:
                continue
            if has_real_cell_after.get(ic):
                continue
            o = by_ic.get(ic)
            if o is None:
                continue
            o.postponement_count = (o.postponement_count or 0) + 1
            store.upsert_officer(o)
            new_teop = compute_tentative_eop(
                posting_start=o.posting_start_date,
                mc_count=leave_counts.get(ic, 0),
                postponement_count=o.postponement_count,
                leave_cap=leave_cap,
            )
            bumped_msgs.append(f"{o.name} → {new_teop.strftime('%d %b %Y')}")

        # Stash alerts in session state so they survive the rerun. The
        # persisted block above renders them on the next pass; they auto-clear
        # as soon as the admin starts editing again (see has_resumed_editing).
        st.session_state.edit_roster_last_save = {
            "saved": saved,
            "blocked_pre": blocked_pre,
            "blocked_post": blocked_post,
            "bumped": bumped_msgs,
        }
        # Bump the editor version so the widget reloads from fresh DB state on
        # rerun. Critical when there were rejections — otherwise the data_editor
        # would still hold the rejected edit and a re-save would re-warn.
        st.session_state.edit_roster_version += 1
        st.cache_data.clear()
        st.rerun()

    # ---- Publish (whenever the current view is a draft) ------------------- #
    if not is_published:
        st.divider()
        cl, cr = st.columns([4, 2])
        cl.warning(
            "📝 This week is a **draft** — the public roster page will not show "
            "it until you publish."
        )
        if cr.button("✅ Publish this week", type="primary",
                     key=f"publish_{monday.isoformat()}"):
            # If the week is an implicit draft (future week, no template yet),
            # snapshot current officer order before flipping the flag.
            if store.get_week_template(monday) is None:
                store.create_week_template(
                    monday=monday,
                    officer_ic_numbers=[o.ic_number for o in officers],
                    actor_email=user.email,
                )
            store.publish_week(monday=monday, actor_email=user.email)
            st.cache_data.clear()
            st.toast(f"Published {week_label(monday)}.", icon="📢")
            st.rerun()

    # ---- Colored preview of the edited week (Overview-style heatmap) ------ #
    preview_rows = []
    for _, r in edited.iterrows():
        ic = r["ic_number"]
        for d, dlabel in zip(days, day_cols):
            code = r[dlabel]
            if not code:
                continue
            s = shifts_by_code.get(code)
            color = (s.color or DUTY_COLORS.get(s.duty_type, "#94a3b8")) if s else "#94a3b8"
            preview_rows.append({
                "ic_number": ic,
                "name": r["name"],
                "on_date": d,
                "shift_code": code,
                "duty_type": s.duty_type if s else "?",
                "ward": s.ward if s else None,
                "hours": s.hours if s else 0,
                "color": color,
            })
    if preview_rows:
        preview_df = pd.DataFrame(preview_rows)
        st.subheader("Color preview")
        st.caption("Mirrors the public Overview's colour-coded view of this week, "
                   "based on the editor above.")
        st.plotly_chart(
            week_grid_figure(preview_df, monday),
            width="stretch", config={"displayModeBar": False},
            key=f"edit_roster_preview_{monday.isoformat()}_{ver}",
        )

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
            # Drop officers whose *real* EOP cell is before next Monday — they've
            # been explicitly marked done. Tentative-only HOs still get carried
            # (admin can extend or finalize them later).
            carried = [
                o.ic_number for o in officers
                if (eop_cell_dates.get(o.ic_number) is None)
                or (eop_cell_dates[o.ic_number] >= next_monday)
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
            key=f"edit_roster_coverage_{monday.isoformat()}",
        )
    with c2:
        st.plotly_chart(
            hours_per_staff_figure(df),
            width="stretch", config={"displayModeBar": False},
            key=f"edit_roster_hours_{monday.isoformat()}",
        )


main()
