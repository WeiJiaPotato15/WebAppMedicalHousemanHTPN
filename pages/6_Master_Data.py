"""Admin: edit the shift code dictionary (Shift, Hours, Duty_Type, Ward).

Seeded with the 37 codes from the Hospital Kajang Grouping sheet at first deploy.
Editable here so the leader can introduce, rename, or retire codes without a redeploy.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import SEED_SHIFTS, now_iso
from lib.db import get_store
from lib.models import AuditEntry, Shift

st.set_page_config(page_title="Master Data — HKJ", page_icon="⚙️", layout="wide")


def main() -> None:
    user = require_admin()
    st.title("⚙️ Master Data — Shift codes")
    st.caption(
        "Each shift code maps to its working hours, duty type (used for color and "
        "category), and ward (used for coverage charts). Hours = 0 means non-working."
    )

    store = get_store()
    shifts = store.list_shifts()

    if not shifts:
        st.warning("No shift codes yet.")
        if st.button(f"Seed {len(SEED_SHIFTS)} default codes from Grouping sheet", type="primary"):
            for s in SEED_SHIFTS:
                store.upsert_shift(Shift(**s))
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="seed_shifts",
                target="shifts:bulk", before="0", after=str(len(SEED_SHIFTS)),
            ))
            st.success("Seeded.")
            st.cache_data.clear()
            st.rerun()
        return

    df = pd.DataFrame([s.model_dump() for s in shifts])
    edited = st.data_editor(
        df,
        column_config={
            "code": st.column_config.TextColumn("Code", disabled=True),
            "hours": st.column_config.NumberColumn("Hours", min_value=0, max_value=24, step=1),
            "duty_type": st.column_config.TextColumn("Duty type"),
            "ward": st.column_config.TextColumn("Ward / location"),
        },
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key="shifts_editor",
    )

    if not edited.equals(df):
        edits = 0
        for i, new_row in edited.iterrows():
            old_row = df.iloc[i]
            if not new_row.equals(old_row):
                store.upsert_shift(Shift(**new_row.to_dict()))
                store.add_audit(AuditEntry(
                    timestamp=now_iso(), actor=user.email, action="upsert_shift",
                    target=f"shift:{new_row['code']}",
                    before=str(old_row.to_dict()), after=str(new_row.to_dict()),
                ))
                edits += 1
        if edits:
            st.toast(f"Saved {edits} change(s).", icon="✅")
            st.cache_data.clear()
            st.rerun()

    with st.expander("➕ Add a new shift code"):
        with st.form("add_shift", clear_on_submit=True):
            c1, c2 = st.columns(2)
            code = c1.text_input("Code (unique)").strip()
            hours = c2.number_input("Hours", min_value=0, max_value=24, value=10, step=1)
            c3, c4 = st.columns(2)
            duty_type = c3.text_input("Duty type (e.g. EH, OH, OC, MOPD, ...)").strip()
            ward = c4.text_input("Ward (e.g. W1, W6, PERI, ED)").strip() or None
            ok = st.form_submit_button("Add", type="primary")
            if ok and code and duty_type:
                store.upsert_shift(Shift(
                    code=code, hours=int(hours), duty_type=duty_type, ward=ward,
                ))
                store.add_audit(AuditEntry(
                    timestamp=now_iso(), actor=user.email, action="upsert_shift",
                    target=f"shift:{code}", before=None, after=f"{duty_type}/{ward}/{hours}h",
                ))
                st.success(f"Added {code}.")
                st.cache_data.clear()
                st.rerun()

    with st.expander("🗑️ Remove a shift code"):
        st.caption("Removing a code does NOT clear historical assignments. Be deliberate.")
        target = st.selectbox("Code to remove", [s.code for s in shifts], key="rm_shift")
        if st.button("Delete", type="secondary"):
            store.delete_shift(target)
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="delete_shift",
                target=f"shift:{target}",
            ))
            st.success(f"Removed {target}.")
            st.cache_data.clear()
            st.rerun()


main()
