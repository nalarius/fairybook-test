"""Activity logging helpers backed by Firestore."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping, MutableMapping, Sequence
from zoneinfo import ZoneInfo

from google_credentials import get_service_account_credentials

try:  # pragma: no cover - optional dependency checked at runtime
    from google.cloud import firestore  # type: ignore
except Exception:  # pragma: no cover - gracefully handle missing package
    firestore = None  # type: ignore

_LOGGER = logging.getLogger(__name__)

ACTIVITY_LOG_ENABLED = (os.getenv("ACTIVITY_LOG_ENABLED", "true").strip().lower() not in {"0", "false", "no"})
_ACTIVITY_COLLECTION_RAW = os.getenv("FIRESTORE_ACTIVITY_COLLECTION", "activity_logs").strip()
ACTIVITY_LOG_COLLECTION = _ACTIVITY_COLLECTION_RAW or "activity_logs"


GCP_PROJECT_ID = (os.getenv("GCP_PROJECT_ID") or "").strip() or None

_ACTIVITY_LOG_ACTIVE = False
_ACTIVITY_DISABLE_REASON: str | None = None

KST = ZoneInfo("Asia/Seoul")


@dataclass(slots=True)
class ActivityLogEntry:
    """Structured representation of an activity log event."""

    id: str
    type: str
    action: str
    result: str
    user_id: str | None
    client_ip: str | None
    timestamp: datetime
    year: int
    month: int
    day: int
    param1: str | None
    param2: str | None
    param3: str | None
    param4: str | None
    param5: str | None
    metadata: Mapping[str, Any] | None


def _ensure_firestore_ready() -> None:
    if firestore is None:
        raise RuntimeError("google-cloud-firestore must be installed for activity logging")

    if GCP_PROJECT_ID:
        return

    credentials = get_service_account_credentials()
    project_id = getattr(credentials, "project_id", "") if credentials else ""
    if project_id:
        return
    raise RuntimeError(
        "Project ID for Firestore activity logging is not configured. Set GCP_PROJECT_ID via environment or credentials."
    )


@lru_cache(maxsize=1)
def _get_firestore_client():
    _ensure_firestore_ready()
    client_kwargs: MutableMapping[str, Any] = {}
    credentials = get_service_account_credentials()
    if credentials is not None:
        client_kwargs["credentials"] = credentials
    if GCP_PROJECT_ID:
        client_kwargs["project"] = GCP_PROJECT_ID
    else:
        credentials_project = getattr(credentials, "project_id", "") if credentials else ""
        if credentials_project:
            client_kwargs["project"] = credentials_project
    return firestore.Client(**client_kwargs)  # type: ignore[arg-type]


def _get_activity_collection():
    client = _get_firestore_client()
    return client.collection(ACTIVITY_LOG_COLLECTION)


def _disable_logging(reason: str) -> None:
    global _ACTIVITY_LOG_ACTIVE, _ACTIVITY_DISABLE_REASON
    if _ACTIVITY_LOG_ACTIVE:
        _LOGGER.warning("Disabling activity logging: %s", reason)
    _ACTIVITY_LOG_ACTIVE = False
    _ACTIVITY_DISABLE_REASON = reason


def init_activity_log() -> None:
    """Prepare Firestore collection access for activity logging."""

    global _ACTIVITY_LOG_ACTIVE
    if not ACTIVITY_LOG_ENABLED:
        _disable_logging("ACTIVITY_LOG_ENABLED is false")
        return

    try:
        collection = _get_activity_collection()
        # Touch the collection by requesting a dummy iterator.
        list(collection.limit(1).stream())  # pragma: no cover - warm up
    except Exception as exc:  # pragma: no cover - initialization failure surfaced later
        _disable_logging(str(exc))
        return

    _ACTIVITY_LOG_ACTIVE = True
    _ACTIVITY_DISABLE_REASON = None
    _LOGGER.debug("Activity logging enabled using Firestore collection '%s'", ACTIVITY_LOG_COLLECTION)


def is_activity_logging_enabled() -> bool:
    return _ACTIVITY_LOG_ACTIVE


def get_activity_logging_status() -> tuple[bool, str | None]:
    return _ACTIVITY_LOG_ACTIVE, _ACTIVITY_DISABLE_REASON


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_result(result: str) -> str:
    normalized = _normalize_string(result).lower()
    if normalized in {"success", "fail"}:
        return normalized
    return "success" if normalized not in {"", "failure", "error"} else "fail"


def log_event(
    *,
    type: str,
    action: str,
    result: str,
    user_id: str | None,
    params: Sequence[str | None] | None = None,
    client_ip: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ActivityLogEntry | None:
    """Emit an activity log event to Firestore.

    Returns the recorded entry on success, or ``None`` when logging is disabled
    or fails. All string inputs are normalized/trimmed before persistence.
    """

    if not _ACTIVITY_LOG_ACTIVE:
        return None

    params = list(params or [])
    while len(params) < 5:
        params.append(None)
    if len(params) > 5:
        params = params[:5]

    now_kst = datetime.now(KST)
    payload: MutableMapping[str, Any] = {
        "type": _normalize_string(type) or "unknown",
        "action": _normalize_string(action) or "unknown",
        "result": _normalize_result(result),
        "user_id": _normalize_string(user_id) or None,
        "client_ip": _normalize_string(client_ip) or None,
        "timestamp": now_kst,
        "timestamp_iso": now_kst.isoformat(),
        "year": now_kst.year,
        "month": now_kst.month,
        "day": now_kst.day,
        "param1": _normalize_string(params[0]) or None,
        "param2": _normalize_string(params[1]) or None,
        "param3": _normalize_string(params[2]) or None,
        "param4": _normalize_string(params[3]) or None,
        "param5": _normalize_string(params[4]) or None,
    }

    if metadata:
        payload["metadata"] = dict(metadata)

    try:
        collection = _get_activity_collection()
        doc_ref = collection.document()
        doc_ref.set(payload)
        return ActivityLogEntry(
            id=str(getattr(doc_ref, "id", "")),
            type=payload["type"],
            action=payload["action"],
            result=payload["result"],
            user_id=payload["user_id"],
            client_ip=payload["client_ip"],
            timestamp=now_kst,
            year=payload["year"],
            month=payload["month"],
            day=payload["day"],
            param1=payload["param1"],
            param2=payload["param2"],
            param3=payload["param3"],
            param4=payload["param4"],
            param5=payload["param5"],
            metadata=dict(metadata) if metadata else None,
        )
    except Exception as exc:  # pragma: no cover - avoid hard failure path in UI
        _disable_logging(str(exc))
        _LOGGER.warning("Failed to log activity event (%s: %s): %s", type, action, exc)
        return None


__all__ = [
    "ActivityLogEntry",
    "ACTIVITY_LOG_COLLECTION",
    "ACTIVITY_LOG_ENABLED",
    "GCP_PROJECT_ID",
    "get_activity_logging_status",
    "init_activity_log",
    "is_activity_logging_enabled",
    "log_event",
]
