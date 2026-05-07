"""Entry point: builds the sidebar navigation. Each page sets its own page_config.

Using st.navigation here so the entry page can be labeled "Overview" in the
sidebar (Streamlit otherwise derives the label from the filename).
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

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
    df = assignments_df(a, s, o)

    if not o:
        st.info(
            "No house officers have been added yet. An admin can add them from the "
            "**Officers** page after signing in."
        )
        return

    # Group officers by ward_group: order rows (ward_group, name) and prefix
    # the name with the ward so the heatmap visibly shows "[W1] Dr. Alice"
    # blocked together, then "[W2] Dr. Ben", then "[PERI] Dr. Chen", etc.
    # Officers without ward_group fall to the bottom under "[—]".
    by_email = {x.email: x for x in o}
    if not df.empty:
        df = df.assign(
            ward_group=df["email"].map(
                lambda e: (by_email[e].ward_group if e in by_email else None)
            )
        )
        df["name"] = df.apply(
            lambda r: f"[{r['ward_group']}] {r['name']}" if r["ward_group"] else f"[—] {r['name']}",
            axis=1,
        )
        df = df.assign(
            __ward_sort=df["ward_group"].fillna("~~~"),
        ).sort_values(["__ward_sort", "name"]).drop(columns="__ward_sort")

    fig = week_grid_figure(df, st.session_state.view_monday)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

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


# ---- Sidebar navigation -------------------------------------------------- #

pages = [
    st.Page(overview, title="Overview", icon="🏥", default=True, url_path="overview"),
    st.Page("pages/1_HO_Stats.py", title="HO Stats", icon="📊"),
    st.Page("pages/2_Login.py", title="Login", icon="🔐"),
    st.Page("pages/3_Edit_Roster.py", title="Edit Roster", icon="📝"),
    st.Page("pages/4_Kanban_View.py", title="Kanban", icon="🎯"),
    st.Page("pages/5_Officers.py", title="Officers", icon="👥"),
    st.Page("pages/6_Master_Data.py", title="Master Data", icon="⚙️"),
    st.Page("pages/7_Admins.py", title="Admins", icon="🛡️"),
    st.Page("pages/8_Activity.py", title="Activity", icon="📜"),
]

st.navigation(pages).run()
