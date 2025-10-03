from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import types

import pytest

fake_streamlit = types.ModuleType("streamlit")
fake_streamlit.session_state = {}
sys.modules.setdefault("streamlit", fake_streamlit)

fake_firebase_admin = types.ModuleType("firebase_admin")
fake_firebase_admin._apps = []
fake_firebase_admin.credentials = types.SimpleNamespace(
    Certificate=lambda path: ("cert", path),
    ApplicationDefault=lambda: ("default"),
)
fake_firebase_admin.auth = types.SimpleNamespace(verify_id_token=lambda token, check_revoked=False: {"uid": "admin"})
fake_firebase_admin.initialize_app = lambda cred, options=None: fake_firebase_admin
fake_firebase_admin.get_app = lambda: fake_firebase_admin
sys.modules.setdefault("firebase_admin", fake_firebase_admin)

from admin_tool import auth as admin_auth
from firebase_auth import AuthSession, FirebaseAuthError


def _build_session(expires_in: timedelta) -> AuthSession:
    return AuthSession(
        uid="admin-uid",
        email="admin@example.com",
        id_token="id-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc) + expires_in,
        display_name="관리자",
        is_email_verified=True,
    )


def test_store_and_clear_admin_session(monkeypatch):
    monkeypatch.setattr(admin_auth.st, "session_state", {})

    session = _build_session(timedelta(hours=1))
    admin_auth.store_admin_session(session)
    assert admin_auth.admin_session_from_state() is not None

    admin_auth.clear_admin_session()
    assert admin_auth.admin_session_from_state() is None


def test_ensure_active_admin_session_refresh(monkeypatch):
    monkeypatch.setattr(admin_auth.st, "session_state", {})

    expired_session = _build_session(timedelta(minutes=-1))
    admin_auth.store_admin_session(expired_session)

    refreshed_session = _build_session(timedelta(hours=2))

    def fake_refresh(token):  # noqa: ARG001
        return refreshed_session

    monkeypatch.setattr(admin_auth, "refresh_id_token", fake_refresh)

    active = admin_auth.ensure_active_admin_session()
    assert active is not None
    assert admin_auth.admin_error_message() is None


def test_ensure_active_admin_session_handles_failure(monkeypatch):
    monkeypatch.setattr(admin_auth.st, "session_state", {})

    expired_session = _build_session(timedelta(minutes=-1))
    admin_auth.store_admin_session(expired_session)

    def fake_refresh(token):  # noqa: ARG001
        raise FirebaseAuthError("failed")

    monkeypatch.setattr(admin_auth, "refresh_id_token", fake_refresh)

    assert admin_auth.ensure_active_admin_session() is None
    assert admin_auth.admin_error_message() == "failed"
