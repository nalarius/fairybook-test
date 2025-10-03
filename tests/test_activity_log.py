from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


def _reload_activity_log(monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    sys.modules.pop("activity_log", None)
    module = importlib.import_module("activity_log")
    return module


def test_activity_logging_disabled_by_env(monkeypatch):
    module = _reload_activity_log(monkeypatch, ACTIVITY_LOG_ENABLED="false")
    module.init_activity_log()
    assert module.is_activity_logging_enabled() is False
    assert module.log_event(type="story", action="noop", result="success", user_id=None) is None


def test_activity_logging_emits_documents(monkeypatch):
    entries: list[tuple[str, dict]] = []

    class FakeDocumentRef:
        def __init__(self, store: list[tuple[str, dict]], doc_id: str):
            self._store = store
            self.id = doc_id

        def set(self, data: dict) -> None:
            self._store.append((self.id, data))

    class FakeQuery:
        def stream(self):  # pragma: no cover - deterministic empty iterator
            return []

        def limit(self, *_):  # pragma: no cover - compatibility shim
            return self

    class FakeCollection:
        def __init__(self, store: list[tuple[str, dict]]):
            self._store = store
            self._counter = 0

        def document(self):
            self._counter += 1
            return FakeDocumentRef(self._store, f"doc{self._counter}")

        def limit(self, *_):
            return FakeQuery()

    class FakeClient:
        def __init__(self, store: list[tuple[str, dict]]):
            self._store = store

        def collection(self, *_):
            return FakeCollection(self._store)

    class FakeFirestore(SimpleNamespace):
        def Client(self, *_, **__):  # pragma: no cover - signature match only
            return FakeClient(entries)

    module = _reload_activity_log(
        monkeypatch,
        ACTIVITY_LOG_ENABLED="true",
        GCP_PROJECT_ID="demo-project",
    )

    fake_firestore = FakeFirestore()
    fake_firestore.Query = SimpleNamespace(DESCENDING="desc")
    monkeypatch.setattr(module, "firestore", fake_firestore, raising=False)
    monkeypatch.setattr(module, "get_service_account_credentials", lambda: SimpleNamespace(project_id="demo-project"))
    module._get_firestore_client.cache_clear()  # type: ignore[attr-defined]

    module.init_activity_log()
    assert module.is_activity_logging_enabled() is True

    entry = module.log_event(
        type="story",
        action="story start",
        result="success",
        user_id="uid-1",
        params=["story-1", "6-8", "모험", "용사 이야기"],
    )
    assert entry is not None
    assert entry.type == "story"
    assert entry.timestamp.tzinfo == ZoneInfo("Asia/Seoul")

    assert entries, "expected activity payload to be written"
    _, payload = entries[0]
    assert payload["type"] == "story"
    assert payload["action"] == "story start"
    assert payload["param2"] == "6-8"


def test_fetch_activity_entries_filters_and_pagination(monkeypatch):
    module = _reload_activity_log(
        monkeypatch,
        ACTIVITY_LOG_ENABLED="true",
        GCP_PROJECT_ID="demo-project",
    )

    now = datetime(2024, 1, 15, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    class FakeDoc:
        def __init__(self, doc_id: str, data: dict):
            self.id = doc_id
            self._data = data

        def to_dict(self) -> dict:
            return dict(self._data)

    docs = [
        FakeDoc(
            "doc1",
            {
                "type": "story",
                "action": "story start",
                "result": "success",
                "timestamp": now,
                "timestamp_iso": now.isoformat(),
                "year": now.year,
                "month": now.month,
                "day": now.day,
                "param1": "story-1",
            },
        ),
        FakeDoc(
            "doc2",
            {
                "type": "moderation",
                "action": "content hide",
                "result": "success",
                "timestamp": now - timedelta(hours=1),
                "timestamp_iso": (now - timedelta(hours=1)).isoformat(),
                "param1": "board_post",
                "param2": "post-1",
                "param3": "spam",
            },
        ),
        FakeDoc(
            "doc3",
            {
                "type": "story",
                "action": "story save",
                "result": "fail",
                "timestamp": now - timedelta(hours=2),
                "timestamp_iso": (now - timedelta(hours=2)).isoformat(),
                "param1": "story-2",
            },
        ),
    ]

    class FakeQuery:
        def __init__(self, records):
            self._records = list(records)
            self._filters: list[tuple[str, str, object]] = []
            self._order_field: str | None = None
            self._direction: str | None = None
            self._limit: int | None = None

        def where(self, field: str, op: str, value):
            self._filters.append((field, op, value))
            return self

        def order_by(self, field: str, direction=None):
            self._order_field = field
            self._direction = direction
            return self

        def limit(self, value: int):
            self._limit = value
            return self

        def stream(self):
            filtered = list(self._records)
            for field, op, value in self._filters:
                if field == "timestamp":
                    if op == ">=":
                        filtered = [doc for doc in filtered if doc.to_dict()[field] >= value]
                    elif op == "<=":
                        filtered = [doc for doc in filtered if doc.to_dict()[field] <= value]
                    elif op == "<":
                        filtered = [doc for doc in filtered if doc.to_dict()[field] < value]
                elif op == "in":
                    filtered = [doc for doc in filtered if doc.to_dict().get(field) in value]

            if self._order_field:
                reverse = str(self._direction or "").upper().startswith("DESC")
                filtered.sort(key=lambda doc: doc.to_dict()[self._order_field], reverse=reverse)

            if self._limit is not None:
                filtered = filtered[: self._limit]

            return filtered

    class FakeCollection:
        def __init__(self, records):
            self._records = records

        def order_by(self, field: str, direction=None):
            query = FakeQuery(self._records)
            return query.order_by(field, direction=direction)

    fake_firestore = SimpleNamespace(Query=SimpleNamespace(DESCENDING="DESCENDING"))
    monkeypatch.setattr(module, "firestore", fake_firestore, raising=False)
    monkeypatch.setattr(module, "_get_activity_collection", lambda: FakeCollection(docs))

    page1 = module.fetch_activity_entries(type_filter=["story"], limit=1)
    assert len(page1.entries) == 1
    assert page1.entries[0].id == "doc1"
    assert page1.has_more is True
    assert page1.next_cursor is not None

    page2 = module.fetch_activity_entries(type_filter=["story"], limit=5, cursor=page1.next_cursor)
    assert [entry.id for entry in page2.entries] == ["doc3"]
    assert page2.has_more is False

    moderation_page = module.fetch_activity_entries(type_filter=["moderation"], action_filter=["content hide"], limit=5)
    assert [entry.id for entry in moderation_page.entries] == ["doc2"]


def test_fetch_activity_entries_validates_inputs(monkeypatch):
    module = _reload_activity_log(
        monkeypatch,
        ACTIVITY_LOG_ENABLED="true",
        GCP_PROJECT_ID="demo-project",
    )

    def _fail_collection():
        raise AssertionError("should not touch collection")

    monkeypatch.setattr(module, "_get_activity_collection", _fail_collection)
    with pytest.raises(ValueError):
        module.fetch_activity_entries(limit=0)

    class RejectingQuery:
        def __init__(self):
            self.where_calls = []

        def where(self, field, op, values):
            self.where_calls.append((field, op, values))
            return self

        def limit(self, *_):
            return self

        def stream(self):  # pragma: no cover - not used
            return []

        def order_by(self, *_ , **__):
            return self

    rejecting_query = RejectingQuery()

    class FakeCollection:
        def order_by(self, *args, **kwargs):
            return rejecting_query.order_by(*args, **kwargs)

    monkeypatch.setattr(module, "firestore", SimpleNamespace(Query=SimpleNamespace(DESCENDING="DESCENDING")), raising=False)
    monkeypatch.setattr(module, "_get_activity_collection", lambda: FakeCollection())

    with pytest.raises(ValueError):
        module.fetch_activity_entries(type_filter=[str(i) for i in range(11)])
