"""Public per-HO self-service stats page. No login required."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.constants import safe_secret
from lib.db import get_store
from lib.constants import LEAVE_DUTY_TYPES
from lib.viz import (
    assignments_df,
    count_leaves,
    days_in_posting,
    leave_dates_figure,
    leave_progress_figure,
    station_mix_donut,
    total_hours,
)

st.set_page_config(page_title="My Stats — HTPN Roster", page_icon="📊", layout="wide")


@st.cache_data(ttl=15)
def _load_for_officer(email: str, start_iso: str, end_iso: str):
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    store = get_store()
    a = store.get_officer_assignments(email, start, end)
    s = store.list_shifts()
    o = store.list_officers()
    return a, s, o


def main() -> None:
    st.title("📊 My Stats")
    st.caption("Pick your name. No login needed.")

    store = get_store()
    officers = store.list_officers()
    if not officers:
        st.info("No house officers registered yet.")
        return

    name_to_email = {o.name: o.email for o in officers}
    pick = st.selectbox("Your name", list(name_to_email.keys()))
    if not pick:
        return
    email = name_to_email[pick]
    me = next(o for o in officers if o.email == email)

    today = date.today()
    a, s, o = _load_for_officer(email, me.posting_start_date.isoformat(), today.isoformat())
    df = assignments_df(a, s, o)

    leaves = count_leaves(df)
    cap = int(safe_secret("app", "leave_cap", 10))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Days in posting", days_in_posting(me))
    m2.metric("Hours so far", f"{total_hours(df)} h")
    m3.metric("EL/MC used", f"{leaves} / {cap}",
              delta=("OK" if leaves < cap else "AT CAP"),
              delta_color=("normal" if leaves < cap else "inverse"))
    m4.metric("Posting started", me.posting_start_date.isoformat())

    if leaves >= cap:
        st.error(f"You have used {leaves} EL/MC days — at or above the {cap}-day cap. "
                 "Speak with your leader.")
    elif leaves >= int(0.8 * cap):
        st.warning(f"You are approaching the {cap}-day EL/MC cap ({leaves} used).")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(leave_progress_figure(leaves, cap), width="stretch",
                        config={"displayModeBar": False})
    with c2:
        st.plotly_chart(station_mix_donut(df), width="stretch",
                        config={"displayModeBar": False})

    st.subheader("EL/MC days taken")
    st.plotly_chart(leave_dates_figure(df), width="stretch",
                    config={"displayModeBar": False})
    leave_rows = df[df["duty_type"].isin(LEAVE_DUTY_TYPES)][
        ["on_date", "shift_code"]
    ].sort_values("on_date").reset_index(drop=True)
    if not leave_rows.empty:
        leave_rows["day"] = pd.to_datetime(leave_rows["on_date"]).dt.day_name()
        leave_rows = leave_rows.rename(
            columns={"on_date": "Date", "shift_code": "Code", "day": "Day"}
        )[["Date", "Day", "Code"]]
        st.dataframe(leave_rows, hide_index=True, width="stretch")

    with st.expander("My recent assignments"):
        if df.empty:
            st.write("No assignments yet.")
        else:
            st.dataframe(
                df.sort_values("on_date", ascending=False)[
                    ["on_date", "shift_code", "duty_type", "ward", "hours"]
                ].reset_index(drop=True),
                width="stretch",
            )


if __name__ == "__main__":
    main()
