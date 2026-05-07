"""Admin login page. The Login button uses Streamlit's native Google OAuth."""
from __future__ import annotations

import streamlit as st

from lib.auth import claim_bootstrap_if_eligible, current_user, login_button, logout_button

st.set_page_config(page_title="Admin Login — HTPN Roster", page_icon="🔐", layout="centered")


def main() -> None:
    st.title("🔐 Admin Login")
    st.write(
        "Only authorized House Officer leaders can edit the roster. "
        "Sign in with your Google email to continue."
    )

    u = current_user()
    if u is None:
        login_button("Sign in with Google")
        st.caption(
            "If this button does nothing, the operator hasn't configured Google OAuth yet. "
            "See the README for setup."
        )
        return

    st.success(f"Signed in as **{u.name}** ({u.email})")
    if u.is_admin:
        role = "Super admin" if u.is_super else "Admin"
        st.info(f"Role: **{role}**. Use the sidebar to navigate to Edit Roster, Officers, etc.")
    elif u.bootstrap_eligible:
        st.warning(
            "No admins exist yet. You can claim the bootstrap super-admin role for this email."
        )
        if st.button("Claim super-admin role", type="primary"):
            claim_bootstrap_if_eligible(u)
            st.success("Claimed. Refreshing…")
            st.rerun()
    else:
        st.error(
            f"{u.email} is not authorized. Ask the bootstrap super-admin to add you "
            "from the Admins page."
        )

    logout_button()


if __name__ == "__main__":
    main()
