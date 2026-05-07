"""Super-admin: manage the admin allowlist."""
from __future__ import annotations

import streamlit as st

from lib.auth import require_super
from lib.constants import now_iso
from lib.db import get_store
from lib.models import Admin, AuditEntry

st.set_page_config(page_title="Admins — HTPN", page_icon="🛡️", layout="centered")


def main() -> None:
    user = require_super()
    st.title("🛡️ Admins")
    st.caption("Only super-admins can promote, demote, or remove admins.")

    store = get_store()
    admins = store.list_admins()

    st.subheader("Current admins")
    if not admins:
        st.write("(none)")
    for a in admins:
        c1, c2, c3, c4 = st.columns([4, 2, 3, 2])
        c1.write(a.email + ("  ⭐" if a.is_bootstrap else ""))
        c2.write(a.role)
        c3.caption(f"added {a.added_at or '—'} by {a.added_by or '—'}")
        if c4.button("Remove", key=f"rm_{a.email}", disabled=(a.email == user.email)):
            store.delete_admin(a.email)
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="remove_admin",
                target=f"admin:{a.email}", before=a.role, after=None,
            ))
            st.success(f"Removed {a.email}.")
            st.cache_data.clear()
            st.rerun()

    st.divider()
    st.subheader("Add an admin")
    with st.form("add_admin", clear_on_submit=True):
        email = st.text_input("Google email").strip().lower()
        role = st.selectbox("Role", ["admin", "super"])
        ok = st.form_submit_button("Add", type="primary")
        if ok and email:
            store.upsert_admin(Admin(
                email=email, role=role,
                added_by=user.email, added_at=now_iso(),
                is_bootstrap=False,
            ))
            store.add_audit(AuditEntry(
                timestamp=now_iso(), actor=user.email, action="add_admin",
                target=f"admin:{email}", before=None, after=role,
            ))
            st.success(f"Added {email} as {role}.")
            st.cache_data.clear()
            st.rerun()

    st.divider()
    st.subheader("Change an admin's role")
    targets = [a for a in admins if a.email != user.email]
    if targets:
        with st.form("change_role"):
            who = st.selectbox("Admin", [a.email for a in targets])
            new_role = st.selectbox("New role", ["admin", "super"])
            ok2 = st.form_submit_button("Update", type="secondary")
            if ok2 and who:
                a = next(x for x in targets if x.email == who)
                store.upsert_admin(Admin(
                    email=a.email, role=new_role,
                    added_by=a.added_by, added_at=a.added_at,
                    is_bootstrap=a.is_bootstrap,
                ))
                store.add_audit(AuditEntry(
                    timestamp=now_iso(), actor=user.email, action="change_role",
                    target=f"admin:{who}", before=a.role, after=new_role,
                ))
                st.success(f"{who} is now {new_role}.")
                st.cache_data.clear()
                st.rerun()


main()
