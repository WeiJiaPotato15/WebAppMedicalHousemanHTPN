"""Public landing page: weekly roster grid for Hospital Kajang Medical Department.

No login required for viewing. Admins click the Login page in the sidebar to edit.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from lib.constants import week_label, week_start
from lib.db import get_store
from lib.viz import assignments_df, week_grid_figure

st.set_page_config(
    page_title="HKJ Medical HO Roster",
    page_icon="🏥",
    layout="wide",
)


@st.cache_data(ttl=10)
def _load_week(monday_iso: str):
    monday = date.fromisoformat(monday_iso)
    store = get_store()
    a = store.get_week_assignments(monday)
    s = store.list_shifts()
    o = store.list_officers()
    return a, s, o


def main() -> None:
    st.title("🏥 Medical Houseman Roster — Hospital Kajang")
    st.caption("Read-only public view. Updated live as the leader edits.")

    # Week navigator
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

    fig = week_grid_figure(df, st.session_state.view_monday)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with st.expander("Legend (duty types)"):
        from lib.constants import DUTY_COLORS
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


if __name__ == "__main__":
    main()
