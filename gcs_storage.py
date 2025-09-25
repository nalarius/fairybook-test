"""Utilities for uploading and listing story exports on Google Cloud Storage."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable

from dotenv import load_dotenv

from google_credentials import get_service_account_credentials

load_dotenv()

logger = logging.getLogger(__name__)

try:  # noqa: SIM105
    from google.cloud import storage  # type: ignore
    from google.api_core.exceptions import GoogleAPIError  # type: ignore
except Exception:  # pragma: no cover - handled gracefully when package missing
    storage = None  # type: ignore

    class GoogleAPIError(Exception):  # type: ignore
        """Fallback error type when google-cloud-storage is unavailable."""

        pass

GCS_BUCKET_NAME = (os.getenv("GCS_BUCKET_NAME") or "").strip()
_GCS_PREFIX_RAW = (os.getenv("GCS_PREFIX") or "").strip()
GCP_PROJECT = (os.getenv("GCP_PROJECT") or "").strip()
_HTML_CONTENT_TYPE = "text/html; charset=utf-8"


def _normalize_prefix(raw: str) -> str:
    prefix = raw.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


GCS_PREFIX = _normalize_prefix(_GCS_PREFIX_RAW)


@dataclass(slots=True)
class GCSExport:
    """Represents a story export stored in Google Cloud Storage."""

    object_name: str
    filename: str
    public_url: str
    updated: datetime | None
    size: int | None


def is_gcs_available() -> bool:
    """Return True if Google Cloud Storage uploads are configured."""

    return bool(storage) and bool(GCS_BUCKET_NAME)


@lru_cache(maxsize=1)
def _get_client() -> Any:
    if not storage:
        raise RuntimeError("google-cloud-storage is not installed")

    client_kwargs: dict[str, str] = {}
    if GCP_PROJECT:
        client_kwargs["project"] = GCP_PROJECT
    credentials = get_service_account_credentials()
    if credentials is not None:
        client_kwargs["credentials"] = credentials
        if not GCP_PROJECT:
            project_id = getattr(credentials, "project_id", "")
            if project_id:
                client_kwargs["project"] = project_id
    return storage.Client(**client_kwargs)  # type: ignore[arg-type]


def _qualify_object_name(filename: str) -> str:
    return f"{GCS_PREFIX}{filename}" if GCS_PREFIX else filename


def upload_html_to_gcs(html: str, filename: str) -> tuple[str, str] | None:
    """Upload HTML content to the configured bucket.

    Returns a tuple of (object_name, public_url) on success, or None when
    GCS is not configured or the upload fails.
    """

    if not is_gcs_available():
        return None

    object_name = _qualify_object_name(filename)
    try:
        client = _get_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(object_name)
        blob.upload_from_string(html, content_type=_HTML_CONTENT_TYPE)
        return object_name, blob.public_url
    except GoogleAPIError as exc:  # pragma: no cover - thin wrapper
        logger.warning("GCS upload failed: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive catch
        logger.warning("Unexpected error uploading to GCS: %s", exc)
    return None


def list_gcs_exports() -> list[GCSExport]:
    """Return the list of HTML exports stored in GCS (most recent first)."""

    if not is_gcs_available():
        return []

    try:
        client = _get_client()
        blobs: Iterable[Any] = client.list_blobs(GCS_BUCKET_NAME, prefix=GCS_PREFIX or None)
    except GoogleAPIError as exc:  # pragma: no cover - network error path
        logger.warning("Failed to list GCS exports: %s", exc)
        return []
    except Exception as exc:  # pragma: no cover - defensive catch
        logger.warning("Unexpected error listing GCS exports: %s", exc)
        return []

    exports: list[GCSExport] = []
    for blob in blobs:
        name = getattr(blob, "name", "")
        if not name.endswith(".html"):
            continue
        filename = name[len(GCS_PREFIX) :] if GCS_PREFIX and name.startswith(GCS_PREFIX) else name
        exports.append(
            GCSExport(
                object_name=name,
                filename=filename,
                public_url=getattr(blob, "public_url", ""),
                updated=getattr(blob, "updated", None),
                size=getattr(blob, "size", None),
            )
        )

    def _sort_key(item: GCSExport) -> datetime:
        return item.updated or datetime.fromtimestamp(0, tz=timezone.utc)

    exports.sort(key=_sort_key, reverse=True)
    return exports


def download_gcs_export(object_name: str) -> str | None:
    """Download HTML content from GCS using the blob's object name."""

    if not is_gcs_available():
        return None

    try:
        client = _get_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(object_name)
        return blob.download_as_text(encoding="utf-8")
    except GoogleAPIError as exc:  # pragma: no cover - network error path
        logger.warning("Failed to download GCS export %s: %s", object_name, exc)
    except Exception as exc:  # pragma: no cover - defensive catch
        logger.warning("Unexpected error downloading GCS export %s: %s", object_name, exc)
    return None


def reset_gcs_client_cache() -> None:
    """Clear the cached storage client (used in tests)."""

    _get_client.cache_clear()


__all__ = [
    "GCSExport",
    "download_gcs_export",
    "is_gcs_available",
    "list_gcs_exports",
    "reset_gcs_client_cache",
    "upload_html_to_gcs",
]
