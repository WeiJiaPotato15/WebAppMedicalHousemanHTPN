"""Admin: manage House Officer records (add/edit/deactivate).

ID is the Malaysian IC number. Ward group is a fixed dropdown of the four
medical wards used at HTPN: W1, W2, W3, W6."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import WARD_GROUPS, now_iso, safe_secret
from lib.db import get_store
from lib.models import AuditEntry, Officer

st.set_page_config(page_title="Officers — HTPN", page_icon="👥", layout="wide")


def main() -> None:
    user = require_admin()
    st.title("👥 House Officers")
    st.caption("Add new HOs, update profiles, deactivate when posting ends.")

    store = get_store()
    officers = store.list_officers()

    # ---- Add form ---------------------------------------------------------- #
    with st.expander("➕ Add a new house officer", expanded=False):
        with st.form("add_ho", clear_on_submit=True):
            c1, c2 = st.columns(2)
            ic_number = c1.text_input(
                "IC number (used as ID)",
                help="Malaysian IC, no dashes — e.g. 990101015555",
            ).strip()
            name = c2.text_input("Full name").strip()
            c3, c4 = st.columns(2)
            posting_start = c3.date_input("Posting start date", value=date.today())
            phone = c4.text_input("Phone")
            c5, c6 = st.columns(2)
            ward_choice = c5.selectbox(
                "Ward group",
                options=[""] + WARD_GROUPS,
                index=0,
                help="Primary ward for row grouping in the roster.",
            )
            posting_number = c6.selectbox(
                "Posting number",
                options=[None, 1, 2, 3, 4, 5, 6],
                format_func=lambda v: "—" if v is None else f"{v}{'st' if v == 1 else 'nd' if v == 2 else 'rd' if v == 3 else 'th'} posting",
                index=0,
                help="Which medical posting this is for the HO (typically 1–6).",
            )
            submitted = st.form_submit_button("Add", type="primary")
            if submitted:
                ward_group = ward_choice or None
                if not ic_number or not name:
                    st.error("IC number and name are required.")
                elif store and any(o.ic_number == ic_number for o in officers):
                    st.error(f"An officer with IC {ic_number} already exists.")
                else:
                    store.upsert_officer(Officer(
                        ic_number=ic_number, name=name, posting_start_date=posting_start,
                        phone=(phone or None), active=True, ward_group=ward_group,
                        posting_number=posting_number,
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

    # ---- Read-only computed summary (always fresh) ------------------------ #
    eop_dates = store.list_eop_dates()
    leave_counts = store.list_leave_counts()
    cap = int(safe_secret("app", "leave_cap", 10))
    summary_df = pd.DataFrame([{
        "Name": o.name,
        "Ward": o.ward_group or "—",
        "Posting #": o.posting_number,
        "Posting start": o.posting_start_date,
        "EOP date": eop_dates.get(o.ic_number),
        f"MC/EL used (cap {cap})": leave_counts.get(o.ic_number, 0),
    } for o in officers])
    st.markdown("##### Computed summary")
    st.caption("EOP date and MC/EL count are derived live from each HO's roster cells.")
    st.dataframe(summary_df, hide_index=True, width="stretch")

    # ---- Bulk edit grid (editable fields only) ---------------------------- #
    st.markdown("##### Edit profiles")
    df = pd.DataFrame([o.model_dump() for o in officers])
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
                options=[None] + WARD_GROUPS,
                help="One of W1, W2, W3, W6.",
            ),
            "posting_number": st.column_config.SelectboxColumn(
                "Posting #",
                options=[None, 1, 2, 3, 4, 5, 6],
                help="Which medical posting (1st–6th).",
            ),
        },
        column_order=("ic_number", "name", "ward_group", "posting_number",
                      "posting_start_date", "phone", "active"),
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
                # pandas represents empty cells as NaN/NaT (float); Pydantic
                # rejects those for Optional[str] / Optional[date]. Coerce
                # missing values to None before constructing the Officer.
                clean = {k: (None if pd.isna(v) else v) for k, v in new_row.to_dict().items()}
                store.upsert_officer(Officer(**clean))
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
