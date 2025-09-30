"""Story export metadata storage helpers."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from google_credentials import get_service_account_credentials

try:  # pragma: no cover - optional dependency checked at runtime
    from google.cloud import firestore  # type: ignore
except Exception:  # pragma: no cover - gracefully handle missing package
    firestore = None  # type: ignore


STORY_LIBRARY_DB_PATH = Path("story_library.db")
_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS story_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    author_name TEXT,
    title TEXT NOT NULL,
    story_id TEXT,
    html_filename TEXT NOT NULL,
    local_path TEXT,
    gcs_object TEXT,
    gcs_url TEXT,
    created_at_utc TEXT NOT NULL
);
"""

_CREATE_INDEX_USER = "CREATE INDEX IF NOT EXISTS idx_story_exports_user ON story_exports (user_id, created_at_utc DESC);"


STORY_STORAGE_MODE = (os.getenv("STORY_STORAGE_MODE") or "remote").strip().lower()
USE_REMOTE_STORY_LIBRARY = STORY_STORAGE_MODE in {"remote", "gcs"}

_PROJECT_ID_RAW = (
    os.getenv("GCP_PROJECT_ID")
    or os.getenv("FIRESTORE_PROJECT_ID")
    or ""
)
GCP_PROJECT_ID = _PROJECT_ID_RAW.strip()

_STORY_COLLECTION_RAW = (os.getenv("FIRESTORE_STORY_COLLECTION") or "stories").strip()
FIRESTORE_STORY_COLLECTION = _STORY_COLLECTION_RAW or "stories"


@dataclass(slots=True)
class StoryRecord:
    """Metadata describing a generated story export."""

    id: str
    story_id: str | None
    user_id: str
    title: str
    html_filename: str
    local_path: str | None
    gcs_object: str | None
    gcs_url: str | None
    author_name: str | None
    created_at_utc: datetime


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_remote_ready() -> None:
    if firestore is None:
        raise RuntimeError("google-cloud-firestore must be installed for remote story storage")

    if GCP_PROJECT_ID:
        return

    credentials = get_service_account_credentials()
    project_id = getattr(credentials, "project_id", "") if credentials else ""
    if not project_id:
        raise RuntimeError(
            "GCP_PROJECT_ID must be set or provided via service-account credentials for story storage."
        )


@lru_cache(maxsize=1)
def _get_firestore_client():
    _ensure_remote_ready()
    client_kwargs: dict[str, object] = {}
    credentials = get_service_account_credentials()
    if credentials is not None:
        client_kwargs["credentials"] = credentials
    if GCP_PROJECT_ID:
        client_kwargs["project"] = GCP_PROJECT_ID
    elif credentials is not None:
        project_id = getattr(credentials, "project_id", "")
        if project_id:
            client_kwargs["project"] = project_id
    return firestore.Client(**client_kwargs)  # type: ignore[arg-type]


def _get_story_collection():
    client = _get_firestore_client()
    return client.collection(FIRESTORE_STORY_COLLECTION)


def _ensure_story_id_column(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(story_exports)")
    }
    if "story_id" not in columns:
        conn.execute("ALTER TABLE story_exports ADD COLUMN story_id TEXT")


def init_story_library(db_path: Path = STORY_LIBRARY_DB_PATH) -> None:
    """Prepare the backing store for story export metadata."""

    if USE_REMOTE_STORY_LIBRARY:
        _ensure_remote_ready()
        _get_story_collection()  # Touch once to validate credentials/collection.
        return

    with _connect(db_path) as conn:
        conn.execute(_TABLE_SCHEMA_SQL)
        _ensure_story_id_column(conn)
        conn.execute(_CREATE_INDEX_USER)
        conn.commit()


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except Exception:  # pragma: no cover - defensive fallback
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _derive_filename(local_path: str | None, gcs_object: str | None) -> str:
    """Return the best-effort filename for a story export."""

    if local_path:
        return Path(local_path).name
    if gcs_object:
        return Path(gcs_object).name
    return "story.html"


def record_story_export(
    *,
    user_id: str,
    title: str,
    local_path: str | None,
    gcs_object: str | None,
    gcs_url: str | None,
    story_id: str | None = None,
    author_name: str | None = None,
    db_path: Path = STORY_LIBRARY_DB_PATH,
) -> StoryRecord:
    """Persist metadata for a newly generated story export."""

    normalized_user = str(user_id or "").strip()
    if not normalized_user:
        raise ValueError("user_id is required to record a story")

    normalized_title = str(title or "").strip() or "제목 없는 동화"
    normalized_author = str(author_name or "").strip() or None
    normalized_local_path = str(local_path).strip() if local_path else None
    normalized_gcs_object = str(gcs_object).strip() if gcs_object else None
    normalized_gcs_url = str(gcs_url).strip() if gcs_url else None
    html_filename = _derive_filename(normalized_local_path, normalized_gcs_object)
    timestamp = datetime.now(timezone.utc)

    if USE_REMOTE_STORY_LIBRARY:
        collection = _get_story_collection()
        doc_ref = collection.document(story_id) if story_id else collection.document()
        assigned_story_id = story_id or str(getattr(doc_ref, "id", ""))
        payload = {
            "user_id": normalized_user,
            "author_name": normalized_author,
            "title": normalized_title,
            "story_id": assigned_story_id,
            "html_filename": html_filename,
            "local_path": normalized_local_path,
            "gcs_object": normalized_gcs_object,
            "gcs_url": normalized_gcs_url,
            "created_at_utc": timestamp,
        }
        doc_ref.set(payload)
        return StoryRecord(
            id=str(getattr(doc_ref, "id", "")),
            story_id=assigned_story_id,
            user_id=normalized_user,
            title=normalized_title,
            html_filename=html_filename,
            local_path=normalized_local_path,
            gcs_object=normalized_gcs_object,
            gcs_url=normalized_gcs_url,
            author_name=normalized_author,
            created_at_utc=timestamp,
        )

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO story_exports (
                user_id,
                author_name,
                title,
                story_id,
                html_filename,
                local_path,
                gcs_object,
                gcs_url,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_user,
                normalized_author,
                normalized_title,
                (story_id or None),
                html_filename,
                normalized_local_path,
                normalized_gcs_object,
                normalized_gcs_url,
                timestamp.isoformat(timespec="seconds"),
            ),
        )
        row_id = cursor.lastrowid
        assigned_story_id = story_id or str(row_id)
        if not story_id:
            conn.execute(
                "UPDATE story_exports SET story_id = ? WHERE id = ?",
                (assigned_story_id, row_id),
            )
        conn.commit()

    return StoryRecord(
        id=str(row_id),
        story_id=assigned_story_id,
        user_id=normalized_user,
        title=normalized_title,
        html_filename=html_filename,
        local_path=normalized_local_path,
        gcs_object=normalized_gcs_object,
        gcs_url=normalized_gcs_url,
        author_name=normalized_author,
        created_at_utc=timestamp,
    )


def _make_story_record(doc_id: str, data: dict) -> StoryRecord:
    resolved_story_id = str(data.get("story_id")) if data.get("story_id") else str(doc_id)
    return StoryRecord(
        id=str(doc_id),
        story_id=resolved_story_id or None,
        user_id=str(data.get("user_id", "")),
        title=str(data.get("title", "")),
        html_filename=str(data.get("html_filename", "story.html")),
        local_path=(str(data.get("local_path")) if data.get("local_path") else None),
        gcs_object=(str(data.get("gcs_object")) if data.get("gcs_object") else None),
        gcs_url=(str(data.get("gcs_url")) if data.get("gcs_url") else None),
        author_name=(str(data.get("author_name")) if data.get("author_name") else None),
        created_at_utc=_coerce_datetime(data.get("created_at_utc")),
    )


def list_story_records(
    *,
    user_id: str | None = None,
    limit: int | None = 50,
    db_path: Path = STORY_LIBRARY_DB_PATH,
) -> list[StoryRecord]:
    """Return story export metadata sorted by recency."""

    if USE_REMOTE_STORY_LIBRARY:
        collection = _get_story_collection()
        if user_id:
            query = collection.where("user_id", "==", user_id)
            documents: Iterable = query.stream()
            records = [
                _make_story_record(getattr(doc, "id", ""), doc.to_dict() or {})
                for doc in documents
            ]
            records.sort(key=lambda item: item.created_at_utc, reverse=True)
            if limit is not None:
                return records[:limit]
            return records

        direction = getattr(getattr(firestore, "Query", None), "DESCENDING", None)
        query = collection.order_by("created_at_utc", direction=direction)
        if limit:
            query = query.limit(limit)

        documents: Iterable = query.stream()
        records: list[StoryRecord] = []
        for doc in documents:
            data = doc.to_dict() or {}
            records.append(_make_story_record(getattr(doc, "id", ""), data))
        return records

    sql = "SELECT * FROM story_exports"
    params: list[object] = []
    if user_id:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " ORDER BY datetime(created_at_utc) DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    records = []
    for row in rows:
        row_story_id = None
        if "story_id" in row.keys():
            value = row["story_id"]
            row_story_id = str(value) if value else None
        if not row_story_id:
            row_story_id = str(row["id"])
        records.append(
            StoryRecord(
                id=str(row["id"]),
                story_id=row_story_id,
                user_id=str(row["user_id"]),
                title=str(row["title"]),
                html_filename=str(row["html_filename"]),
                local_path=(str(row["local_path"]) if row["local_path"] else None),
                gcs_object=(str(row["gcs_object"]) if row["gcs_object"] else None),
                gcs_url=(str(row["gcs_url"]) if row["gcs_url"] else None),
                author_name=(str(row["author_name"]) if row["author_name"] else None),
                created_at_utc=_coerce_datetime(row["created_at_utc"]),
            )
        )
    return records


def reset_story_library_cache() -> None:
    """Testing helper to reset cached Firestore clients."""

    _get_firestore_client.cache_clear()


__all__ = [
    "StoryRecord",
    "init_story_library",
    "list_story_records",
    "record_story_export",
    "reset_story_library_cache",
]
