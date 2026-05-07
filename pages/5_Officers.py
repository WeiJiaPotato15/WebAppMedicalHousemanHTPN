"""Admin: manage House Officer records (add/edit/deactivate)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import now_iso
from lib.db import get_store
from lib.models import AuditEntry, Officer

st.set_page_config(page_title="Officers — HKJ", page_icon="👥", layout="wide")


def main() -> None:
    user = require_admin()
    st.title("👥 House Officers")
    st.caption("Add new HOs, update profiles, deactivate when posting ends.")

    store = get_store()

    with st.expander("➕ Add a new house officer", expanded=False):
        with st.form("add_ho", clear_on_submit=True):
            c1, c2 = st.columns(2)
            email = c1.text_input("Email (used as ID)").strip().lower()
            name = c2.text_input("Full name").strip()
            c3, c4, c5, c6 = st.columns(4)
            posting_start = c3.date_input("Posting start date", value=date.today())
            ic_last4 = c4.text_input("IC last 4 digits", max_chars=4)
            phone = c5.text_input("Phone")
            ward_group = c6.text_input(
                "Ward group", help="Primary ward for row grouping in the roster (e.g. W1, W2, MOPD, PERI)."
            ).strip() or None
            submitted = st.form_submit_button("Add", type="primary")
            if submitted:
                if not email or not name:
                    st.error("Email and name are required.")
                else:
                    store.upsert_officer(Officer(
                        email=email, name=name, posting_start_date=posting_start,
                        ic_last4=(ic_last4 or None), phone=(phone or None), active=True,
                        ward_group=ward_group,
                    ))
                    store.add_audit(AuditEntry(
                        timestamp=now_iso(), actor=user.email, action="upsert_officer",
                        target=f"officer:{email}", before=None, after=name,
                    ))
                    st.success(f"Added {name}.")
                    st.cache_data.clear()
                    st.rerun()

    officers = store.list_officers()
    if not officers:
        st.info("No officers yet — add one above.")
        return

    df = pd.DataFrame([o.model_dump() for o in officers])
    edited = st.data_editor(
        df,
        column_config={
            "email": st.column_config.TextColumn("Email", disabled=True),
            "name": st.column_config.TextColumn("Name"),
            "posting_start_date": st.column_config.DateColumn("Posting start"),
            "ic_last4": st.column_config.TextColumn("IC last 4", max_chars=4),
            "phone": st.column_config.TextColumn("Phone"),
            "active": st.column_config.CheckboxColumn("Active"),
            "ward_group": st.column_config.TextColumn(
                "Ward group", help="W1, W2, MOPD, PERI, … — primary row grouping in the roster."
            ),
        },
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key="officers_editor",
    )

    if not edited.equals(df):
        edits = 0
        for i, new_row in edited.iterrows():
            old_row = df.iloc[i]
            if not new_row.equals(old_row):
                store.upsert_officer(Officer(**new_row.to_dict()))
                store.add_audit(AuditEntry(
                    timestamp=now_iso(), actor=user.email, action="upsert_officer",
                    target=f"officer:{new_row['email']}",
                    before=str(old_row.to_dict()), after=str(new_row.to_dict()),
                ))
                edits += 1
        if edits:
            st.toast(f"Saved {edits} officer change(s).", icon="✅")
            st.cache_data.clear()
            st.rerun()

    with st.expander("🗑️ Remove an officer"):
        st.caption("Removing deletes the officer record and orphans existing assignments. "
                   "Prefer setting Active = false unless they were added in error.")
        target = st.selectbox("Officer to remove", [o.email for o in officers], key="rm_off")
        if st.button("Delete", type="secondary"):
            store.delete_officer(target)
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="delete_officer",
                target=f"officer:{target}",
            ))
            st.success(f"Removed {target}.")
            st.cache_data.clear()
            st.rerun()


main()
