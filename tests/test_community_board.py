from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


def reload_board(monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    sys.modules.pop("community_board", None)
    module = importlib.import_module("community_board")
    return module


def test_local_board_sqlite(tmp_path, monkeypatch):
    module = reload_board(monkeypatch, STORY_STORAGE_MODE="local")
    test_db = tmp_path / "board.db"

    module.init_board_store(db_path=test_db)
    module.add_post(user_id="Alice", content="Hello", client_ip="1.1.1.1", db_path=test_db)
    module.add_post(user_id="Bob", content=" 또 만나요 ", client_ip=None, db_path=test_db)

    posts = module.list_posts(limit=5, db_path=test_db)
    assert len(posts) == 2
    assert posts[0].user_id == "Bob"
    assert posts[1].content == "Hello"
    assert posts[0].client_ip is None or posts[0].client_ip == "None"


def test_remote_board_firestore(monkeypatch):
    class FakeDocumentSnapshot:
        def __init__(self, doc_id: str, data: dict):
            self.id = doc_id
            self._data = data

        def to_dict(self) -> dict:
            return self._data

    class FakeBackend:
        def __init__(self):
            self.documents: list[tuple[str, dict]] = []

    backend = FakeBackend()

    class FakeDocumentRef:
        def __init__(self, collection: "FakeCollection", doc_id: str):
            self.collection = collection
            self.id = doc_id

        def set(self, data: dict) -> None:
            self.collection.backend.documents.append((self.id, data))

    class FakeQuery:
        def __init__(self, backend: FakeBackend, field: str, direction: str | None):
            self.backend = backend
            self.field = field
            self.direction = direction
            self._limit: int | None = None

        def limit(self, value: int) -> "FakeQuery":
            self._limit = value
            return self

        def stream(self):
            reverse = self.direction == FakeFirestore.Query.DESCENDING
            sorted_docs = sorted(
                self.backend.documents,
                key=lambda item: item[1].get(self.field),
                reverse=reverse,
            )
            if self._limit is not None:
                sorted_docs = sorted_docs[: self._limit]
            return [FakeDocumentSnapshot(doc_id, data) for doc_id, data in sorted_docs]

    class FakeCollection:
        def __init__(self, backend: FakeBackend):
            self.backend = backend
            self._counter = 0

        def document(self):
            self._counter += 1
            return FakeDocumentRef(self, f"doc{self._counter}")

        def order_by(self, field: str, direction: str | None = None) -> FakeQuery:
            return FakeQuery(self.backend, field, direction)

    class FakeClient:
        def __init__(self, backend: FakeBackend):
            self.backend = backend

        def collection(self, name: str):  # pragma: no cover - name unused but kept for fidelity
            return FakeCollection(self.backend)

    class FakeFirestore(SimpleNamespace):
        Query = SimpleNamespace(DESCENDING="desc")

        def __init__(self, backend: FakeBackend):
            super().__init__()
            self.backend = backend

        def Client(self, *_, **__):
            return FakeClient(self.backend)

    module = reload_board(
        monkeypatch,
        STORY_STORAGE_MODE="remote",
        GCP_PROJECT_ID="test-project",
        FIRESTORE_COLLECTION="posts",
    )

    fake_firestore = FakeFirestore(backend)
    monkeypatch.setattr(module, "firestore", fake_firestore, raising=False)
    module.reset_board_storage_cache()

    module.init_board_store()
    module.add_post(user_id="Alice", content="첫 글", client_ip="127.0.0.1")
    module.add_post(user_id="Bob", content="둘째 글", client_ip=None)

    posts = module.list_posts(limit=10)
    assert {post.user_id for post in posts} == {"Alice", "Bob"}
    assert posts[0].created_at_utc >= posts[1].created_at_utc
