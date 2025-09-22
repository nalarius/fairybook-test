"""Lightweight community board datastore helpers."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

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


@dataclass(slots=True)
class BoardPost:
    """Representation of a single board post."""

    id: int
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


def init_board_store(db_path: Path = BOARD_DB_PATH) -> None:
    """Ensure the SQLite database and table exist."""
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
) -> None:
    """Persist a new board post.

    Raises ValueError if the provided user id or content is empty after trimming.
    """
    normalized_user = str(user_id).strip()
    normalized_content = str(content).strip()

    if not normalized_user:
        raise ValueError("user id is required")
    if not normalized_content:
        raise ValueError("content is required")

    if max_content_length and len(normalized_content) > max_content_length:
        normalized_content = normalized_content[:max_content_length]

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO board_posts (user_id, content, client_ip, created_at_utc)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_user, normalized_content, client_ip, timestamp),
        )
        conn.commit()


def list_posts(*, limit: int = 50, db_path: Path = BOARD_DB_PATH) -> list[BoardPost]:
    """Return the most recent board posts."""
    if limit <= 0:
        return []

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
        raw_created = row["created_at_utc"]
        created_at: datetime
        if isinstance(raw_created, datetime):
            created_at = raw_created
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            try:
                created_at = datetime.fromisoformat(str(raw_created))
            except ValueError:
                created_at = datetime.now(timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

        posts.append(
            BoardPost(
                id=int(row["id"]),
                user_id=str(row["user_id"]),
                content=str(row["content"]),
                client_ip=str(row["client_ip"]) if row["client_ip"] is not None else None,
                created_at_utc=created_at,
            )
        )
    return posts
