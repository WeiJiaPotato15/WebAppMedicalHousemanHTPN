"""Admin: manage House Officer records (add/edit/deactivate).

ID is the Malaysian IC number. Ward group is a dropdown sourced from existing
officer ward_groups + ward attributes from the shift master, plus a sentinel
"+ Add new..." option that reveals a free-text input."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import now_iso
from lib.db import get_store
from lib.models import AuditEntry, Officer

st.set_page_config(page_title="Officers — HTPN", page_icon="👥", layout="wide")
ADD_NEW_SENTINEL = "+ Add new ward group…"


def _ward_group_options(officers: list[Officer], shifts) -> list[str]:
    """Build a sorted list of distinct ward group choices for the dropdown."""
    from_officers = {o.ward_group for o in officers if o.ward_group}
    from_shifts = {s.ward for s in shifts if s.ward and "+" not in s.ward}
    options = sorted(from_officers | from_shifts, key=_ward_sort_key)
    return options


def _ward_sort_key(w: str):
    if w.startswith("W") and w[1:].isdigit():
        return (0, int(w[1:]))
    return (1, w)


def main() -> None:
    user = require_admin()
    st.title("👥 House Officers")
    st.caption("Add new HOs, update profiles, deactivate when posting ends.")

    store = get_store()
    officers = store.list_officers()
    shifts = store.list_shifts()
    ward_options = _ward_group_options(officers, shifts)

    # ---- Add form ---------------------------------------------------------- #
    with st.expander("➕ Add a new house officer", expanded=False):
        with st.form("add_ho", clear_on_submit=True):
            c1, c2 = st.columns(2)
            ic_number = c1.text_input(
                "IC number (used as ID)",
                help="Malaysian IC, no dashes — e.g. 990101015555",
            ).strip()
            name = c2.text_input("Full name").strip()
            c3, c4, c5 = st.columns(3)
            posting_start = c3.date_input("Posting start date", value=date.today())
            phone = c4.text_input("Phone")
            ward_choice = c5.selectbox(
                "Ward group",
                options=[""] + ward_options + [ADD_NEW_SENTINEL],
                index=0,
                help="Primary ward for row grouping in the roster.",
            )
            ward_new = ""
            if ward_choice == ADD_NEW_SENTINEL:
                ward_new = st.text_input("New ward group name").strip()
            submitted = st.form_submit_button("Add", type="primary")
            if submitted:
                ward_group = (ward_new or None) if ward_choice == ADD_NEW_SENTINEL else (ward_choice or None)
                if not ic_number or not name:
                    st.error("IC number and name are required.")
                elif store and any(o.ic_number == ic_number for o in officers):
                    st.error(f"An officer with IC {ic_number} already exists.")
                else:
                    store.upsert_officer(Officer(
                        ic_number=ic_number, name=name, posting_start_date=posting_start,
                        phone=(phone or None), active=True, ward_group=ward_group,
                    ))
                    store.add_audit(AuditEntry(
                        timestamp=now_iso(), actor=user.email, action="upsert_officer",
                        target=f"officer:{ic_number}", before=None, after=name,
                    ))
                    st.success(f"Added {name}.")
                    st.cache_data.clear()
                    st.rerun()

    if not officers:
        st.info("No officers yet — add one above.")
        return

    # ---- Bulk edit grid --------------------------------------------------- #
    eop_dates = store.list_eop_dates()
    df = pd.DataFrame([o.model_dump() for o in officers])
    df["eop_date"] = df["ic_number"].map(lambda ic: eop_dates.get(ic))
    edited = st.data_editor(
        df,
        column_config={
            "ic_number": st.column_config.TextColumn("IC number", disabled=True),
            "name": st.column_config.TextColumn("Name"),
            "posting_start_date": st.column_config.DateColumn("Posting start"),
            "phone": st.column_config.TextColumn("Phone"),
            "active": st.column_config.CheckboxColumn("Active"),
            "ward_group": st.column_config.SelectboxColumn(
                "Ward group",
                options=[None] + ward_options,
                help="W1, W2, MOPD, PERI, … (add new ones via the form above).",
            ),
            "eop_date": st.column_config.DateColumn(
                "EOP date (auto)", disabled=True,
                help="Earliest date you assigned the EOP shift to this HO. Updates automatically.",
            ),
        },
        column_order=("ic_number", "name", "ward_group", "posting_start_date",
                      "phone", "active", "eop_date"),
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
                    target=f"officer:{new_row['ic_number']}",
                    before=str(old_row.to_dict()), after=str(new_row.to_dict()),
                ))
                edits += 1
        if edits:
            st.toast(f"Saved {edits} officer change(s).", icon="✅")
            st.cache_data.clear()
            st.rerun()

    # ---- Delete -----------------------------------------------------------#
    with st.expander("🗑️ Remove an officer"):
        st.caption("Removing deletes the officer record and orphans existing assignments. "
                   "Prefer setting Active = false unless they were added in error.")
        ic_to_label = {o.ic_number: f"{o.name} ({o.ic_number})" for o in officers}
        target = st.selectbox(
            "Officer to remove",
            options=list(ic_to_label.keys()),
            format_func=lambda ic: ic_to_label[ic],
            key="rm_off",
        )
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
