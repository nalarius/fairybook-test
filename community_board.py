"""Lightweight community board datastore helpers with dual backends."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from google_credentials import get_service_account_credentials

try:  # pragma: no cover - optional dependency checked at runtime
    from google.cloud import firestore  # type: ignore
except Exception:  # pragma: no cover - gracefully handle missing package
    firestore = None  # type: ignore

BOARD_DB_PATH = Path("board.db")
_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS board_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    client_ip TEXT,
    created_at_utc TEXT NOT NULL
);
"""

_STORY_STORAGE_MODE = (os.getenv("STORY_STORAGE_MODE") or "remote").strip().lower()
USE_REMOTE_BOARD = _STORY_STORAGE_MODE in {"remote", "gcs"}

_PROJECT_ID_RAW = (
    os.getenv("GCP_PROJECT_ID")
    or os.getenv("FIRESTORE_PROJECT_ID")
    or ""
)
GCP_PROJECT_ID = _PROJECT_ID_RAW.strip()
_FIRESTORE_COLLECTION_RAW = (os.getenv("FIRESTORE_COLLECTION") or "posts").strip()
FIRESTORE_COLLECTION = _FIRESTORE_COLLECTION_RAW or "posts"


@dataclass(slots=True)
class BoardPost:
    """Representation of a single board post."""

    id: str
    user_id: str
    content: str
    client_ip: str | None
    created_at_utc: datetime


class SupportsStripped(Protocol):
    def strip(self) -> str: ...


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_remote_ready() -> None:
    if firestore is None:
        raise RuntimeError("google-cloud-firestore must be installed for remote board storage")

    if GCP_PROJECT_ID:
        return

    credentials = get_service_account_credentials()
    project_id = getattr(credentials, "project_id", "") if credentials else ""
    if not project_id:
        raise RuntimeError(
            "GCP_PROJECT_ID must be set or provided via service-account credentials for the board."
        )


@lru_cache(maxsize=1)
def _get_firestore_client():
    _ensure_remote_ready()
    client_kwargs: dict[str, str] = {}
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


def _get_firestore_collection():
    client = _get_firestore_client()
    return client.collection(FIRESTORE_COLLECTION)


def reset_board_storage_cache() -> None:
    """Testing helper to reset cached Firestore clients."""

    _get_firestore_client.cache_clear()


def init_board_store(db_path: Path = BOARD_DB_PATH) -> None:
    """Prepare the persistence layer for the community board."""

    if USE_REMOTE_BOARD:
        _ensure_remote_ready()
        _get_firestore_collection()  # Touch once to validate credentials/collection.
        return

    with _connect(db_path) as conn:
        conn.execute(_TABLE_SCHEMA_SQL)
        conn.commit()


def add_post(
    *,
    user_id: SupportsStripped,
    content: SupportsStripped,
    client_ip: str | None,
    db_path: Path = BOARD_DB_PATH,
    max_content_length: int = 1000,
) -> str:
    """Persist a new board post via the configured backend and return its identifier."""

    normalized_user = str(user_id).strip()
    normalized_content = str(content).strip()

    if not normalized_user:
        raise ValueError("user id is required")
    if not normalized_content:
        raise ValueError("content is required")

    if max_content_length and len(normalized_content) > max_content_length:
        normalized_content = normalized_content[:max_content_length]

    timestamp = datetime.now(timezone.utc)

    if USE_REMOTE_BOARD:
        collection = _get_firestore_collection()
        doc_ref = collection.document()
        doc_ref.set(
            {
                "user_id": normalized_user,
                "content": normalized_content,
                "client_ip": client_ip,
                "created_at_utc": timestamp,
            }
        )
        return str(getattr(doc_ref, "id", ""))

    timestamp_iso = timestamp.isoformat(timespec="seconds")
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO board_posts (user_id, content, client_ip, created_at_utc)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_user, normalized_content, client_ip, timestamp_iso),
        )
        conn.commit()
        row_id = cursor.lastrowid
    return str(row_id)


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


def list_posts(*, limit: int = 50, db_path: Path = BOARD_DB_PATH) -> list[BoardPost]:
    """Return the most recent board posts from the configured backend."""

    if limit <= 0:
        return []

    if USE_REMOTE_BOARD:
        collection = _get_firestore_collection()
        direction = getattr(getattr(firestore, "Query", None), "DESCENDING", None)
        query = collection.order_by("created_at_utc", direction=direction).limit(limit)
        documents = list(query.stream())

        posts: list[BoardPost] = []
        for doc in documents:
            data = doc.to_dict() or {}
            posts.append(
                BoardPost(
                    id=str(getattr(doc, "id", "")),
                    user_id=str(data.get("user_id", "")),
                    content=str(data.get("content", "")),
                    client_ip=data.get("client_ip"),
                    created_at_utc=_coerce_datetime(data.get("created_at_utc")),
                )
            )
        return posts

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, user_id, content, client_ip, created_at_utc
            FROM board_posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    posts: list[BoardPost] = []
    for row in rows:
        created_at = _coerce_datetime(row["created_at_utc"])

        posts.append(
            BoardPost(
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                content=str(row["content"]),
                client_ip=str(row["client_ip"]) if row["client_ip"] is not None else None,
                created_at_utc=created_at,
            )
        )
    return posts


__all__ = [
    "BoardPost",
    "add_post",
    "init_board_store",
    "list_posts",
    "reset_board_storage_cache",
]
