"""Admin: audit log (who changed what, when)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.db import get_store

st.set_page_config(page_title="Activity — HKJ", page_icon="📜", layout="wide")


def main() -> None:
    require_admin()
    st.title("📜 Activity log")
    st.caption("Every roster, officer, shift, and admin change is recorded here.")

    today = date.today()
    default_ym = today.strftime("%Y-%m")
    ym = st.text_input("Year-Month (YYYY-MM)", value=default_ym, max_chars=7)

    store = get_store()
    entries = store.list_audit(ym, limit=500)

    if not entries:
        st.info(f"No activity for {ym}.")
        return

    df = pd.DataFrame([e.model_dump() for e in entries])
    actors = sorted(df["actor"].unique().tolist())
    actions = sorted(df["action"].unique().tolist())
    c1, c2 = st.columns(2)
    f_actor = c1.multiselect("Filter actor", actors)
    f_action = c2.multiselect("Filter action", actions)
    if f_actor:
        df = df[df["actor"].isin(f_actor)]
    if f_action:
        df = df[df["action"].isin(f_action)]
    st.dataframe(df.reset_index(drop=True), use_container_width=True, hide_index=True)


main()
