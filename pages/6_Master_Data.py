"""Admin: edit the shift code dictionary (Shift, Hours, Duty_Type, Ward, Color).

Seeded with the 37 codes from the Hospital Tengku Permaisuri Norashikin Grouping
sheet at first deploy. Editable here so the leader can introduce, rename, retire
codes, or recolor them on the Overview without a redeploy.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from lib.auth import require_admin
from lib.constants import DUTY_COLORS, SEED_SHIFTS, now_iso
from lib.db import get_store
from lib.models import AuditEntry, Shift

st.set_page_config(page_title="Master Data — HTPN", page_icon="⚙️", layout="wide")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _effective_color(s: Shift) -> str:
    return s.color or DUTY_COLORS.get(s.duty_type, "#94a3b8")


def main() -> None:
    user = require_admin()
    st.title("⚙️ Master Data — Shift codes")
    st.caption(
        "Each shift code maps to its working hours, duty type, ward, and color. "
        "Hours = 0 means non-working. Color is what shows on the public Overview "
        "heatmap; leave blank to use the duty-type default."
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

    # ---- Color preview (read-only swatches) ------------------------------- #
    st.markdown("##### Effective colors on the Overview")
    preview = pd.DataFrame([{
        "Code": s.code,
        "Duty type": s.duty_type,
        "Ward": s.ward or "—",
        "Hours": s.hours,
        "Color": _effective_color(s),
        "Source": "custom" if s.color else "duty-type default",
    } for s in shifts])

    def _swatch_style(row):
        color = row["Color"]
        # Color the "Color" cell with the actual hex, plus contrast text
        return [
            "", "", "", "",
            f"background-color: {color}; color: white; font-weight: 600",
            "",
        ]

    st.dataframe(
        preview.style.apply(_swatch_style, axis=1),
        hide_index=True, width="stretch",
    )

    # ---- Editable grid ---------------------------------------------------- #
    st.markdown("##### Edit shifts")
    df = pd.DataFrame([s.model_dump() for s in shifts])
    edited = st.data_editor(
        df,
        column_config={
            "code": st.column_config.TextColumn("Code", disabled=True),
            "hours": st.column_config.NumberColumn("Hours", min_value=0, max_value=24, step=1),
            "duty_type": st.column_config.TextColumn("Duty type"),
            "ward": st.column_config.TextColumn("Ward / location"),
            "color": st.column_config.TextColumn(
                "Color (hex)",
                help="6-digit hex like #0f766e. Blank = use the duty-type default.",
                max_chars=7,
            ),
        },
        column_order=("code", "duty_type", "ward", "hours", "color"),
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key="shifts_editor",
    )

    if not edited.equals(df):
        edits = 0
        bad_color: list[str] = []
        for i, new_row in edited.iterrows():
            old_row = df.iloc[i]
            if new_row.equals(old_row):
                continue
            clean = {k: (None if pd.isna(v) else v) for k, v in new_row.to_dict().items()}
            color = clean.get("color")
            if color and not HEX_RE.match(color):
                bad_color.append(f"{clean['code']} ({color!r})")
                continue
            store.upsert_shift(Shift(**clean))
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="upsert_shift",
                target=f"shift:{new_row['code']}",
                before=str(old_row.to_dict()), after=str(new_row.to_dict()),
            ))
            edits += 1
        if edits:
            st.toast(f"Saved {edits} change(s).", icon="✅")
        if bad_color:
            st.error(
                f"Rejected {len(bad_color)} bad color value(s) — must be a "
                "6-digit hex like #0f766e: " + ", ".join(bad_color[:5])
            )
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
            c5, c6 = st.columns(2)
            use_default = c5.checkbox("Use duty-type default color", value=True)
            picked = c6.color_picker(
                "Custom color",
                value=DUTY_COLORS.get(duty_type, "#0ea5e9"),
                disabled=use_default,
            )
            ok = st.form_submit_button("Add", type="primary")
            if ok and code and duty_type:
                color = None if use_default else picked
                store.upsert_shift(Shift(
                    code=code, hours=int(hours), duty_type=duty_type,
                    ward=ward, color=color,
                ))
                store.add_audit(AuditEntry(
                    timestamp=now_iso(), actor=user.email, action="upsert_shift",
                    target=f"shift:{code}",
                    before=None,
                    after=f"{duty_type}/{ward}/{hours}h/{color or 'default'}",
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
