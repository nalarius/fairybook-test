from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo


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
