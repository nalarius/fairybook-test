"""Helpers for loading Google service account credentials flexibly."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from google.oauth2 import service_account  # type: ignore
    from google.auth.credentials import Credentials  # type: ignore
except Exception:  # pragma: no cover - degrade gracefully when package missing
    service_account = None  # type: ignore

    class Credentials:  # type: ignore[override]
        """Fallback stub when google-auth is unavailable."""

        pass

_SECRET_KEYS = (
    "google_credentials",
    "gcp_service_account",
    "service_account",
)
_REQUIRED_FIELDS = {"type", "project_id", "private_key", "client_email"}
_DEFAULT_CREDENTIAL_FILE = Path("google-credential.json")


def _load_json_mapping(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _normalize_mapping(candidate: Any) -> dict[str, Any] | None:
    if candidate is None:
        return None
    if isinstance(candidate, Mapping):
        return {str(key): value for key, value in candidate.items()}
    if hasattr(candidate, "keys") and hasattr(candidate, "items"):
        try:
            return {str(key): candidate[key] for key in candidate.keys()}
        except Exception:  # pragma: no cover - defensive
            pass
    if isinstance(candidate, str):
        candidate = candidate.strip()
        if not candidate:
            return None
        return _load_json_mapping(candidate)
    return None


def _service_account_info_from_streamlit() -> dict[str, Any] | None:
    try:
        import streamlit as st
    except Exception:  # pragma: no cover - streamlit not installed in tests
        return None

    secrets = getattr(st, "secrets", None)
    if secrets is None:
        return None

    for key in _SECRET_KEYS:
        section = secrets.get(key) if hasattr(secrets, "get") else None
        if section is None:
            try:
                section = secrets[key]
            except Exception:  # pragma: no cover - fallback path
                section = None
        info = _normalize_mapping(section)
        if info and _REQUIRED_FIELDS.issubset(info.keys()):
            return info  # Found structured section.

    # Fall back to root-level secrets if they directly contain the fields.
    info = _normalize_mapping(secrets)
    if info and _REQUIRED_FIELDS.issubset(info.keys()):
        return info

    # Fall back to JSON string stored under GOOGLE_CREDENTIALS secret.
    json_blob = secrets.get("GOOGLE_CREDENTIALS_JSON") if hasattr(secrets, "get") else None
    if json_blob is None:
        try:
            json_blob = secrets["GOOGLE_CREDENTIALS_JSON"]
        except Exception:  # pragma: no cover - fallback path
            json_blob = None
    info = _normalize_mapping(json_blob)
    if info and _REQUIRED_FIELDS.issubset(info.keys()):
        return info

    return None


def _service_account_info_from_env() -> dict[str, Any] | None:
    env_keys = (
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "GCP_SERVICE_ACCOUNT_INFO",
    )
    for env_key in env_keys:
        blob = os.getenv(env_key)
        if not blob:
            continue
        info = _normalize_mapping(blob)
        if info and _REQUIRED_FIELDS.issubset(info.keys()):
            return info
    return None


def _service_account_path_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(_DEFAULT_CREDENTIAL_FILE)
    return candidates


def _credentials_from_file() -> Credentials | None:
    if service_account is None:
        return None

    for path in _service_account_path_candidates():
        try:
            if path.is_file():
                return service_account.Credentials.from_service_account_file(str(path))
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.warning("Failed to load Google credentials from %s: %s", path, exc)
    return None


def _credentials_from_info(info: Mapping[str, Any]) -> Credentials | None:
    if service_account is None:
        return None

    try:
        return service_account.Credentials.from_service_account_info(dict(info))
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning("Failed to construct Google credentials from mapping: %s", exc)
    return None


@lru_cache(maxsize=1)
def get_service_account_credentials() -> Credentials | None:
    """Return service-account credentials from env, secrets, or bundled file."""

    credentials = _credentials_from_file()
    if credentials is not None:
        return credentials

    info = _service_account_info_from_env()
    if info:
        credentials = _credentials_from_info(info)
        if credentials is not None:
            return credentials

    info = _service_account_info_from_streamlit()
    if info:
        credentials = _credentials_from_info(info)
        if credentials is not None:
            return credentials

    return None


__all__ = ["get_service_account_credentials", "Credentials"]
