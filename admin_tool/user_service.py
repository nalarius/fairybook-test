"""Firebase Admin helpers for the Streamlit admin console."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from firebase_admin import auth as admin_auth

from firebase_auth import ensure_firebase_admin_initialized


@dataclass(slots=True)
class AdminUser:
    uid: str
    email: str | None
    display_name: str | None
    disabled: bool
    role: str | None
    custom_claims: Mapping[str, Any]
    created_at: datetime | None
    last_sign_in: datetime | None
    sanction: Mapping[str, Any] | None


def _ensure_admin() -> None:
    ensure_firebase_admin_initialized()


def _millis_to_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    seconds = millis / 1000
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _serialize_user(record: Any) -> AdminUser:
    claims = dict(record.custom_claims or {})
    metadata = getattr(record, "user_metadata", None)
    created_at = _millis_to_datetime(getattr(metadata, "creation_timestamp", None))
    last_sign_in = _millis_to_datetime(getattr(metadata, "last_sign_in_timestamp", None))

    return AdminUser(
        uid=getattr(record, "uid", ""),
        email=getattr(record, "email", None),
        display_name=getattr(record, "display_name", None),
        disabled=bool(getattr(record, "disabled", False)),
        role=str(claims.get("role") or "") or None,
        custom_claims=claims,
        created_at=created_at,
        last_sign_in=last_sign_in,
        sanction=claims.get("sanction"),
    )


def _unique_records(records: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for record in records:
        uid = getattr(record, "uid", "")
        if uid and uid not in seen:
            seen.add(uid)
            unique.append(record)
    return unique


def search_user(term: str) -> list[AdminUser]:
    """Attempt to resolve a single user by uid/email/phone."""

    cleaned = term.strip()
    if not cleaned:
        return []

    _ensure_admin()

    candidates: list[Any] = []

    try:
        candidates.append(admin_auth.get_user(cleaned))
    except admin_auth.UserNotFoundError:
        pass

    if "@" in cleaned:
        try:
            candidates.append(admin_auth.get_user_by_email(cleaned))
        except admin_auth.UserNotFoundError:
            pass

    if cleaned.startswith("+"):
        try:
            candidates.append(admin_auth.get_user_by_phone_number(cleaned))
        except admin_auth.UserNotFoundError:
            pass

    return [_serialize_user(record) for record in _unique_records(candidates)]


def _normalize_role_filter(role: str | None) -> str | None:
    if role is None:
        return None
    normalized = role.strip().lower()
    if not normalized or normalized == "all":
        return None
    return normalized


def _filter_users_by_role(users: Sequence[AdminUser], role: str | None) -> list[AdminUser]:
    normalized = _normalize_role_filter(role)
    if normalized is None:
        return list(users)
    if normalized == "none":
        return [user for user in users if not user.role]
    return [user for user in users if (user.role or "").lower() == normalized]


def list_users(
    *,
    page_size: int = 50,
    page_token: str | None = None,
    search: str | None = None,
    query: str | None = None,
    role: str | None = None,
) -> tuple[list[AdminUser], str | None]:
    """Return a page of users, optionally short-circuiting with search and role filters."""

    if page_size <= 0 or page_size > 1000:
        raise ValueError("page_size must be between 1 and 1000")

    search_term = (search or query or "").strip()
    role_filter = role

    if search_term:
        results = search_user(search_term)
        if results:
            return _filter_users_by_role(results, role_filter), None

    _ensure_admin()
    page = admin_auth.list_users(page_token=page_token, max_results=page_size)
    users = [_serialize_user(record) for record in getattr(page, "users", [])]
    next_token = getattr(page, "next_page_token", None)
    return _filter_users_by_role(users, role_filter), next_token


def set_user_disabled(uid: str, disabled: bool) -> AdminUser:
    _ensure_admin()
    record = admin_auth.update_user(uid, disabled=disabled)
    return _serialize_user(record)


def set_user_role(uid: str, role: str | None) -> AdminUser:
    _ensure_admin()

    record = admin_auth.get_user(uid)
    claims = dict(record.custom_claims or {})
    if role:
        claims["role"] = role
    else:
        claims.pop("role", None)
    admin_auth.set_custom_user_claims(uid, claims)
    refreshed = admin_auth.get_user(uid)
    return _serialize_user(refreshed)


def generate_password_reset(email: str) -> str:
    _ensure_admin()
    return admin_auth.generate_password_reset_link(email)


def _duration_to_timedelta(duration: str) -> timedelta | None:
    mapping = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    return mapping.get(duration)


def apply_user_sanction(
    uid: str,
    *,
    sanction_type: str,
    duration: str,
    reason: str,
    note: str | None,
    context_id: str | None,
    applied_by: str | None,
) -> tuple[AdminUser, Mapping[str, Any] | None]:
    """Apply or clear a sanction by updating the user's custom claims."""

    _ensure_admin()
    record = admin_auth.get_user(uid)
    claims = dict(record.custom_claims or {})

    if sanction_type == "unban":
        claims.pop("sanction", None)
        admin_auth.set_custom_user_claims(uid, claims)
        refreshed = admin_auth.get_user(uid)
        return _serialize_user(refreshed), None

    sanction_payload: dict[str, Any] = {
        "type": sanction_type,
        "duration": duration,
        "reason": reason,
        "note": note or "",
        "context_id": context_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "applied_by": applied_by,
    }

    delta = _duration_to_timedelta(duration)
    if delta is not None:
        sanction_payload["expires_at"] = (datetime.now(timezone.utc) + delta).isoformat()

    claims["sanction"] = sanction_payload
    admin_auth.set_custom_user_claims(uid, claims)
    refreshed = admin_auth.get_user(uid)
    return _serialize_user(refreshed), sanction_payload


__all__ = [
    "AdminUser",
    "list_users",
    "search_user",
    "set_user_disabled",
    "set_user_role",
    "generate_password_reset",
    "apply_user_sanction",
]
