from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone, timedelta


def _load_story_library(monkeypatch, mode: str = "local"):
    monkeypatch.setenv("STORY_STORAGE_MODE", mode)
    module_name = "story_library"
    if module_name in sys.modules:
        sys.modules.pop(module_name)
    return importlib.import_module(module_name)


def test_list_story_records_filters_by_user(monkeypatch, tmp_path):
    db_path = tmp_path / "stories.db"
    lib = _load_story_library(monkeypatch)

    lib.init_story_library(db_path=db_path)

    record_kwargs = {
        "local_path": None,
        "gcs_object": None,
        "gcs_url": None,
        "db_path": db_path,
    }

    lib.record_story_export(user_id="user-1", title="첫 번째", **record_kwargs)
    lib.record_story_export(user_id="user-2", title="두 번째", **record_kwargs)
    lib.record_story_export(user_id="user-1", title="세 번째", **record_kwargs)

    # Normalize timestamps to enforce predictable ordering
    base = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    overrides = {
        "첫 번째": base + timedelta(minutes=1),
        "두 번째": base + timedelta(minutes=2),
        "세 번째": base + timedelta(minutes=3),
    }
    with lib._connect(db_path) as conn:  # type: ignore[attr-defined]
        for title, ts in overrides.items():
            conn.execute(
                "UPDATE story_exports SET created_at_utc = ? WHERE title = ?",
                (ts.isoformat(), title),
            )
        conn.commit()

    all_records = lib.list_story_records(db_path=db_path)
    assert [record.title for record in all_records] == ["세 번째", "두 번째", "첫 번째"]
    assert [record.user_id for record in all_records] == ["user-1", "user-2", "user-1"]

    user_records = lib.list_story_records(user_id="user-1", db_path=db_path)
    assert {record.user_id for record in user_records} == {"user-1"}
    assert [record.title for record in user_records] == ["세 번째", "첫 번째"]


def test_list_story_records_limit(monkeypatch, tmp_path):
    db_path = tmp_path / "stories.db"
    lib = _load_story_library(monkeypatch)
    lib.init_story_library(db_path=db_path)

    record_kwargs = {
        "local_path": None,
        "gcs_object": None,
        "gcs_url": None,
        "db_path": db_path,
    }

    for idx in range(5):
        lib.record_story_export(user_id="user", title=f"story-{idx}", **record_kwargs)

    with lib._connect(db_path) as conn:  # type: ignore[attr-defined]
        base = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)
        for idx in range(5):
            ts = base + timedelta(minutes=idx)
            conn.execute(
                "UPDATE story_exports SET created_at_utc = ? WHERE title = ?",
                (ts.isoformat(), f"story-{idx}"),
            )
        conn.commit()

    limited = lib.list_story_records(user_id="user", limit=2, db_path=db_path)
    assert len(limited) == 2
    assert [record.title for record in limited] == ["story-4", "story-3"]
