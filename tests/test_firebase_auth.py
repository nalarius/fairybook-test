from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
import types

import pytest


def reload_firebase_auth(monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    sys.modules.pop("firebase_auth", None)

    try:
        import firebase_admin  # noqa: F401
    except ModuleNotFoundError:
        fake_admin = types.ModuleType("firebase_admin")
        fake_admin._apps = []
        fake_admin.credentials = SimpleNamespace(
            Certificate=lambda path: ("cert", path),
            ApplicationDefault=lambda: ("default"),
        )
        fake_admin.auth = SimpleNamespace(verify_id_token=lambda token, check_revoked=False: {
            "uid": "fake",
            "token": token,
            "revoked": check_revoked,
        })

        def initialize_app(_cred, _options=None):
            fake_admin._apps.append(object())
            return fake_admin

        fake_admin.initialize_app = initialize_app
        fake_admin.get_app = lambda: fake_admin
        monkeypatch.setitem(sys.modules, "firebase_admin", fake_admin)

    return importlib.import_module("firebase_auth")


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def test_sign_up_success(monkeypatch):
    module = reload_firebase_auth(monkeypatch, FIREBASE_WEB_API_KEY="dummy-key")

    def fake_post(url, json=None, data=None, params=None, timeout=None):  # noqa: ARG001
        assert "key=dummy-key" in url
        assert json["email"] == "kid@example.com"
        return FakeResponse(
            200,
            {
                "localId": "uid-123",
                "email": "kid@example.com",
                "displayName": "Young Author",
                "idToken": "id-token",
                "refreshToken": "refresh-token",
                "expiresIn": "3600",
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post)

    session = module.sign_up("kid@example.com", "secret123", display_name="Young Author")
    assert session.uid == "uid-123"
    assert session.email == "kid@example.com"
    assert session.display_name == "Young Author"
    assert session.id_token == "id-token"
    assert session.refresh_token == "refresh-token"
    assert session.expires_in.total_seconds() > 0


def test_sign_in_error_maps_firebase_code(monkeypatch):
    module = reload_firebase_auth(monkeypatch, FIREBASE_WEB_API_KEY="dummy-key")

    def fake_post(url, json=None, data=None, params=None, timeout=None):  # noqa: ARG001
        return FakeResponse(400, {"error": {"message": "INVALID_PASSWORD"}})

    monkeypatch.setattr(module.requests, "post", fake_post)

    with pytest.raises(module.FirebaseAuthError) as excinfo:
        module.sign_in("kid@example.com", "badpass")
    assert excinfo.value.code == "INVALID_PASSWORD"


def test_refresh_id_token(monkeypatch):
    module = reload_firebase_auth(monkeypatch, FIREBASE_WEB_API_KEY="dummy-key")

    def fake_post(url, json=None, data=None, params=None, timeout=None):  # noqa: ARG001
        assert params == {"key": "dummy-key"}
        assert data["grant_type"] == "refresh_token"
        return FakeResponse(
            200,
            {
                "user_id": "uid-123",
                "email": "kid@example.com",
                "id_token": "new-id-token",
                "refresh_token": "new-refresh",
                "expires_in": "3600",
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post)

    session = module.refresh_id_token("refresh-token")
    assert session.uid == "uid-123"
    assert session.id_token == "new-id-token"
    assert session.refresh_token == "new-refresh"


def test_verify_id_token_delegates_to_admin(monkeypatch):
    module = reload_firebase_auth(monkeypatch, FIREBASE_WEB_API_KEY="dummy-key")

    called = SimpleNamespace(init=False, token=None, revoked=None)

    monkeypatch.setattr(module, "_ensure_firebase_admin_initialized", lambda: setattr(called, "init", True))

    def fake_verify(token, check_revoked=False):
        called.token = token
        called.revoked = check_revoked
        return {"uid": "uid-123"}

    monkeypatch.setattr(module.admin_auth, "verify_id_token", fake_verify)

    result = module.verify_id_token("id-token", check_revoked=True)
    assert result == {"uid": "uid-123"}
    assert called.init is True
    assert called.token == "id-token"
    assert called.revoked is True
