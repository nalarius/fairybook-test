from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def _normalize(value: str | None) -> str:
    return (value or "").strip()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def generate_story_id(
    *,
    age: str | None,
    topic: str | None,
    started_at: datetime | None = None,
) -> tuple[str, str]:
    """Return a deterministic story identifier and UTC timestamp seed.

    The identifier is derived from user-provided context (age, topic)
    combined with the UTC moment the story flow started. This keeps the
    ID stable for the remainder of the session without inventing an
    arbitrary session identifier.
    """

    base_timestamp = _ensure_utc(started_at or datetime.now(timezone.utc))
    started_at_iso = base_timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z")

    payload = {
        "age": _normalize(age) or "unknown-age",
        "topic": _normalize(topic),
        "started_at": started_at_iso,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest, started_at_iso


__all__ = ["generate_story_id"]
