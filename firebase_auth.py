"""Lightweight Firebase Authentication helpers (signup/signin/refresh)."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import firebase_admin
import requests
from firebase_admin import auth as admin_auth, credentials


logger = logging.getLogger(__name__)

FIREBASE_WEB_API_KEY = (os.getenv("FIREBASE_WEB_API_KEY") or "").strip()

_IDENTITY_BASE_URL = "https://identitytoolkit.googleapis.com/v1"
_SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token"


class FirebaseAuthError(RuntimeError):
    """Raised when the Firebase Identity Toolkit returns an error."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class AuthSession:
    """Normalized response for sign-up/sign-in/refresh flows."""

    uid: str
    email: str
    id_token: str
    refresh_token: str
    expires_at: datetime
    display_name: str | None = None
    is_email_verified: bool = False

    @property
    def expires_in(self) -> timedelta:
        return max(self.expires_at - datetime.now(timezone.utc), timedelta(0))


def _require_api_key() -> str:
    if not FIREBASE_WEB_API_KEY:
        raise RuntimeError("FIREBASE_WEB_API_KEY is not configured; cannot call Firebase Identity Toolkit.")
    return FIREBASE_WEB_API_KEY


def _build_url(endpoint: str) -> str:
    key = _require_api_key()
    return f"{_IDENTITY_BASE_URL}/{endpoint}?key={key}"


def _post_json(url: str, payload: Mapping[str, Any]) -> MutableMapping[str, Any]:
    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - network issues
        raise FirebaseAuthError(f"Network error contacting Firebase Identity Toolkit: {exc}") from exc

    try:
        data = response.json()
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise FirebaseAuthError("Invalid response from Firebase Identity Toolkit (non-JSON body)") from exc

    if response.status_code >= 400:
        error = data.get("error") if isinstance(data, Mapping) else None
        message = None
        code = None
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("message", "")
            code = message
        raise FirebaseAuthError(message or "Firebase auth request failed", code=code)

    if not isinstance(data, MutableMapping):
        raise FirebaseAuthError("Unexpected Firebase response shape")
    return data


def _parse_auth_session(data: Mapping[str, Any]) -> AuthSession:
    expires_in_raw = str(data.get("expiresIn") or data.get("expires_in") or "3600")
    try:
        expires_seconds = int(expires_in_raw)
    except ValueError:  # pragma: no cover - defensive
        expires_seconds = 3600

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)

    return AuthSession(
        uid=str(data.get("localId") or data.get("user_id") or ""),
        email=str(data.get("email") or ""),
        id_token=str(data.get("idToken") or data.get("id_token") or ""),
        refresh_token=str(data.get("refreshToken") or data.get("refresh_token") or ""),
        expires_at=expires_at,
        display_name=data.get("displayName"),
        is_email_verified=bool(data.get("emailVerified") or data.get("is_email_verified")),
    )


def sign_up(email: str, password: str, *, display_name: str | None = None) -> AuthSession:
    """Register a new Firebase Authentication user using email/password."""

    payload: dict[str, Any] = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
    }
    if display_name:
        payload["displayName"] = display_name

    data = _post_json(_build_url("accounts:signUp"), payload)
    return _parse_auth_session(data)


def sign_in(email: str, password: str) -> AuthSession:
    """Authenticate an existing Firebase user using email/password."""

    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
    }
    data = _post_json(_build_url("accounts:signInWithPassword"), payload)
    return _parse_auth_session(data)


def refresh_id_token(refresh_token: str) -> AuthSession:
    """Refresh an ID token using the Secure Token endpoint."""

    key = _require_api_key()
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        response = requests.post(_SECURETOKEN_URL, params={"key": key}, data=payload, timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - network issues
        raise FirebaseAuthError(f"Network error contacting Secure Token API: {exc}") from exc

    try:
        data = response.json()
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise FirebaseAuthError("Invalid response from Secure Token API (non-JSON body)") from exc

    if response.status_code >= 400:
        error_description = data.get("error_description") if isinstance(data, Mapping) else None
        raise FirebaseAuthError(error_description or "Failed to refresh Firebase ID token")

    if not isinstance(data, Mapping):
        raise FirebaseAuthError("Unexpected Secure Token response shape")

    session_payload = {
        "localId": data.get("user_id"),
        "email": data.get("email", ""),
        "idToken": data.get("id_token"),
        "refreshToken": data.get("refresh_token"),
        "expiresIn": data.get("expires_in"),
        "is_email_verified": data.get("is_new_user") is False,
    }
    return _parse_auth_session(session_payload)


def update_profile(id_token: str, *, display_name: str | None = None) -> AuthSession:
    """Update user profile fields (currently display_name)."""

    payload: dict[str, Any] = {
        "idToken": id_token,
        "returnSecureToken": True,
    }
    if display_name is not None:
        payload["displayName"] = display_name

    data = _post_json(_build_url("accounts:update"), payload)
    return _parse_auth_session(data)


def _resolve_service_account_path() -> Path | None:
    candidates = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        os.getenv("FIREBASE_SERVICE_ACCOUNT"),
    )
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_file():
            return path
    return None


def _resolve_project_id() -> str | None:
    project_id = (os.getenv("GCP_PROJECT_ID") or os.getenv("GCP_PROJECT") or "").strip()
    return project_id or None


def _ensure_firebase_admin_initialized() -> firebase_admin.App:
    if firebase_admin._apps:  # type: ignore[attr-defined]
        return firebase_admin.get_app()

    service_account_path = _resolve_service_account_path()
    project_id = _resolve_project_id()

    options: dict[str, Any] = {}
    if project_id:
        options["projectId"] = project_id

    if service_account_path and service_account_path.is_file():
        cred = credentials.Certificate(str(service_account_path))
        return firebase_admin.initialize_app(cred, options or None)

    try:
        cred = credentials.ApplicationDefault()
    except Exception as exc:  # pragma: no cover - defensive logging
        raise RuntimeError(
            "Firebase Admin SDK could not initialize. Provide GOOGLE_APPLICATION_CREDENTIALS or "
            "FIREBASE_SERVICE_ACCOUNT pointing to a service-account JSON file."
        ) from exc

    return firebase_admin.initialize_app(cred, options or None)


def verify_id_token(id_token: str, *, check_revoked: bool = False) -> Mapping[str, Any]:
    """Verify an ID token using firebase_admin, returning the decoded claims."""

    _ensure_firebase_admin_initialized()
    return admin_auth.verify_id_token(id_token, check_revoked=check_revoked)


def ensure_firebase_admin_initialized() -> firebase_admin.App:
    """Public accessor for ensuring the Firebase Admin SDK is ready."""

    return _ensure_firebase_admin_initialized()


__all__ = [
    "AuthSession",
    "FirebaseAuthError",
    "refresh_id_token",
    "sign_in",
    "sign_up",
    "update_profile",
    "verify_id_token",
    "ensure_firebase_admin_initialized",
]
