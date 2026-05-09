"""Entry point: builds the sidebar navigation. Each page sets its own page_config.

Using st.navigation here so the entry page can be labeled "Overview" in the
sidebar (Streamlit otherwise derives the label from the filename).
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from lib.auth import current_user
from lib.constants import DUTY_COLORS, week_label, week_start
from lib.db import get_store
from lib.viz import assignments_df, week_grid_figure


@st.cache_data(ttl=10)
def _load_week(monday_iso: str):
    monday = date.fromisoformat(monday_iso)
    store = get_store()
    a = store.get_week_assignments(monday)
    s = store.list_shifts()
    o = store.list_officers()
    return a, s, o


def overview() -> None:
    """Public read-only weekly roster grid."""
    st.set_page_config(
        page_title="HTPN Medical HO Roster",
        page_icon="🏥",
        layout="wide",
    )
    st.title("🏥 Medical Houseman Roster — Hospital Tengku Permaisuri Norashikin")
    st.caption("Read-only public view. Updated live as the leader edits.")

    if "view_monday" not in st.session_state:
        st.session_state.view_monday = week_start(date.today())

    col_prev, col_label, col_next, col_today = st.columns([1, 4, 1, 1])
    with col_prev:
        if st.button("◀ Prev"):
            st.session_state.view_monday -= timedelta(days=7)
    with col_next:
        if st.button("Next ▶"):
            st.session_state.view_monday += timedelta(days=7)
    with col_today:
        if st.button("Today"):
            st.session_state.view_monday = week_start(date.today())
    with col_label:
        st.subheader(f"Week of {week_label(st.session_state.view_monday)}")

    a, s, o = _load_week(st.session_state.view_monday.isoformat())

    # Hide drafts from public viewers.
    if not get_store().is_week_published(st.session_state.view_monday):
        st.info(
            "📝 This week's roster is being prepared by the admins and is not "
            "yet published. Check back soon, or use **Prev**/**Today** to see "
            "the most recent published week."
        )
        return

    df = assignments_df(a, s, o)

    if not o:
        st.info(
            "No house officers have been added yet. An admin can add them from the "
            "**Officers** page after signing in."
        )
        return

    # Annotate every assignment row with its officer's ward_group, then split
    # into one heatmap per ward. "W"-numeric wards come first in numeric order
    # (W1, W2, W3, W6 …), other wards alphabetical, ungrouped last.
    by_ic = {x.ic_number: x for x in o}
    if df.empty:
        st.info("No assignments yet for this week.")
    else:
        df = df.assign(
            ward_group=df["ic_number"].map(
                lambda ic: (by_ic[ic].ward_group if ic in by_ic else None)
            )
        )

        def _ward_sort_key(w: str) -> tuple[int, int | str]:
            if w and w.startswith("W") and w[1:].isdigit():
                return (0, int(w[1:]))
            return (1, w or "~~~")

        wards = sorted(
            (w for w in df["ward_group"].unique() if w),
            key=_ward_sort_key,
        )
        for ward in wards:
            sub = df[df["ward_group"] == ward].sort_values("name")
            st.markdown(f"#### Ward {ward}" if ward.startswith("W") and ward[1:].isdigit() else f"#### {ward}")
            fig = week_grid_figure(sub, st.session_state.view_monday)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False},
                            key=f"grid_{ward}_{st.session_state.view_monday.isoformat()}")

        ungrouped = df[df["ward_group"].isna()]
        if not ungrouped.empty:
            st.markdown("#### Ungrouped")
            st.caption("These officers don't have a Ward group set yet — admins can fix this on the Officers page.")
            sub = ungrouped.sort_values("name")
            fig = week_grid_figure(sub, st.session_state.view_monday)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False},
                            key=f"grid_ungrouped_{st.session_state.view_monday.isoformat()}")

    with st.expander("Legend (duty types)"):
        cols = st.columns(4)
        for i, (k, v) in enumerate(DUTY_COLORS.items()):
            with cols[i % 4]:
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;background:{v};"
                    f"border-radius:3px;margin-right:6px;'></span>{k}",
                    unsafe_allow_html=True,
                )

    st.divider()
    st.caption(
        "Looking at your own posting stats? Open **HO Stats** in the sidebar — "
        "no login needed."
    )


# ---- Sidebar greeting (shows on every page) ----------------------------- #

def _render_sidebar_user() -> None:
    u = current_user()
    with st.sidebar:
        if u is None:
            st.caption("Not signed in.")
        else:
            st.markdown(f"**Hi, {u.email}**")
            if u.is_super:
                st.caption("🛡️ super admin")
            elif u.is_admin:
                st.caption("👤 admin")
            else:
                st.caption("👁️ signed in")
            if st.button("Sign out", key="sb_signout", width="stretch"):
                try:
                    st.logout()
                except Exception:
                    pass
        st.divider()


_render_sidebar_user()


# ---- Sidebar navigation -------------------------------------------------- #

pages = [
    st.Page(overview, title="Overview", icon="🏥", default=True, url_path="overview"),
    st.Page("pages/1_HO_Stats.py", title="HO Stats", icon="📊"),
    st.Page("pages/2_Login.py", title="Login", icon="🔐"),
    st.Page("pages/3_Edit_Roster.py", title="Edit Roster", icon="📝"),
    st.Page("pages/5_Officers.py", title="Officers", icon="👥"),
    st.Page("pages/6_Master_Data.py", title="Master Data", icon="⚙️"),
    st.Page("pages/7_Admins.py", title="Admins", icon="🛡️"),
    st.Page("pages/8_Activity.py", title="Activity", icon="📜"),
]

st.navigation(pages).run()
