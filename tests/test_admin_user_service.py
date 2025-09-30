from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys
import types

import pytest

fake_firebase_admin = types.ModuleType("firebase_admin")
fake_firebase_admin._apps = []
fake_firebase_admin.auth = SimpleNamespace(UserNotFoundError=Exception)
fake_firebase_admin.credentials = SimpleNamespace(
    Certificate=lambda path: ("cert", path),
    ApplicationDefault=lambda: ("default"),
)
fake_firebase_admin.initialize_app = lambda cred, options=None: fake_firebase_admin
fake_firebase_admin.get_app = lambda: fake_firebase_admin
sys.modules.setdefault("firebase_admin", fake_firebase_admin)

from admin_tool import user_service


class FakeUserRecord(SimpleNamespace):
    pass


def _make_record(uid="uid-1", *, custom_claims=None):
    metadata = SimpleNamespace(creation_timestamp=1_000, last_sign_in_timestamp=2_000)
    return FakeUserRecord(
        uid=uid,
        email=f"{uid}@example.com",
        display_name=f"User {uid}",
        disabled=False,
        custom_claims=custom_claims or {},
        user_metadata=metadata,
    )


def test_list_users_returns_serialized_records(monkeypatch):
    record = _make_record()
    fake_page = SimpleNamespace(users=[record], next_page_token="next-token")

    class FakeAdmin:
        UserNotFoundError = Exception

        def list_users(self, **kwargs):  # noqa: ARG002
            return fake_page

    monkeypatch.setattr(user_service, "ensure_firebase_admin_initialized", lambda: None)
    monkeypatch.setattr(user_service, "admin_auth", FakeAdmin())

    users, next_token = user_service.list_users(page_size=10)
    assert len(users) == 1
    assert users[0].uid == record.uid
    assert next_token == "next-token"


def test_list_users_search_short_circuits(monkeypatch):
    record = _make_record()

    class FakeAdmin:
        UserNotFoundError = Exception

        def __init__(self):
            self.list_called = False

        def get_user(self, term):  # noqa: ARG002
            return record

        def list_users(self, **kwargs):  # noqa: ARG002
            self.list_called = True
            return SimpleNamespace(users=[], next_page_token=None)

    fake_admin = FakeAdmin()
    monkeypatch.setattr(user_service, "ensure_firebase_admin_initialized", lambda: None)
    monkeypatch.setattr(user_service, "admin_auth", fake_admin)

    users, token = user_service.list_users(search="uid-1")
    assert len(users) == 1
    assert token is None
    assert fake_admin.list_called is False


def test_set_user_role_updates_claims(monkeypatch):
    initial = _make_record(custom_claims={})
    updated = _make_record(custom_claims={"role": "admin"})

    class FakeAdmin:
        UserNotFoundError = Exception

        def __init__(self):
            self.claims = None

        def get_user(self, uid):  # noqa: ARG002
            return initial if self.claims is None else updated

        def set_custom_user_claims(self, uid, claims):  # noqa: ARG002
            self.claims = claims

    fake_admin = FakeAdmin()
    monkeypatch.setattr(user_service, "ensure_firebase_admin_initialized", lambda: None)
    monkeypatch.setattr(user_service, "admin_auth", fake_admin)

    result = user_service.set_user_role("uid-1", "admin")
    assert result.role == "admin"
    assert fake_admin.claims == {"role": "admin"}


def test_apply_user_sanction(monkeypatch):
    initial = _make_record(custom_claims={})

    class FakeAdmin:
        UserNotFoundError = Exception

        def __init__(self):
            self.claims = None

        def get_user(self, uid):  # noqa: ARG002
            if self.claims is None:
                return initial
            return _make_record(custom_claims=self.claims)

        def set_custom_user_claims(self, uid, claims):  # noqa: ARG002
            self.claims = claims

    fake_admin = FakeAdmin()
    monkeypatch.setattr(user_service, "ensure_firebase_admin_initialized", lambda: None)
    monkeypatch.setattr(user_service, "admin_auth", fake_admin)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):  # noqa: ARG002
            return datetime(2024, 1, 1, tzinfo=timezone.utc)

        @staticmethod
        def fromtimestamp(value, tz=None):  # noqa: ARG002
            return datetime.fromtimestamp(value, tz=timezone.utc if tz is None else tz)

    monkeypatch.setattr(user_service, "datetime", FakeDateTime)

    updated, sanction = user_service.apply_user_sanction(
        "uid-1",
        sanction_type="ban",
        duration="24h",
        reason="spam",
        note="테스트",
        context_id="post-1",
        applied_by="admin@example.com",
    )

    assert updated.sanction is not None
    assert sanction["reason"] == "spam"
    assert fake_admin.claims["sanction"]["type"] == "ban"

    updated2, sanction2 = user_service.apply_user_sanction(
        "uid-1",
        sanction_type="unban",
        duration="permanent",
        reason="",
        note=None,
        context_id=None,
        applied_by="admin@example.com",
    )
    assert sanction2 is None
    assert updated2.sanction is None
