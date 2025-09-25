from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import gcs_storage


class StubClientFactory:
    """Callable wrapper that mimics functools.lru_cache cache_clear API."""

    def __init__(self, client):
        self.client = client

    def __call__(self):
        return self.client

    def cache_clear(self):
        pass


def configure_storage(monkeypatch, *, bucket: str = "bucket", prefix: str = "") -> None:
    monkeypatch.setattr(gcs_storage, "GCS_BUCKET_NAME", bucket, raising=False)
    monkeypatch.setattr(gcs_storage, "GCS_PREFIX", prefix, raising=False)
    monkeypatch.setattr(gcs_storage, "GCP_PROJECT", "", raising=False)
    monkeypatch.setattr(gcs_storage, "storage", SimpleNamespace(Client=object), raising=False)
    gcs_storage.reset_gcs_client_cache()


def test_upload_html_to_gcs_success(monkeypatch):
    configure_storage(monkeypatch, prefix="exports/")

    class RecordingBlob:
        def __init__(self, name: str):
            self.name = name
            self.public_url = f"https://storage.googleapis.com/test/{name}"
            self.calls: list[tuple[str, str]] = []

        def upload_from_string(self, data: str, **kwargs) -> None:
            self.calls.append((data, kwargs.get("content_type")))

    class StubBucket:
        def __init__(self) -> None:
            self.blobs: dict[str, RecordingBlob] = {}

        def blob(self, object_name: str) -> RecordingBlob:
            blob = self.blobs.setdefault(object_name, RecordingBlob(object_name))
            return blob

    bucket = StubBucket()

    class StubClient:
        def bucket(self, bucket_name: str) -> StubBucket:
            assert bucket_name == "bucket"
            return bucket

    monkeypatch.setattr(gcs_storage, "_get_client", StubClientFactory(StubClient()), raising=False)

    result = gcs_storage.upload_html_to_gcs("<html></html>", "story.html")

    assert result == ("exports/story.html", "https://storage.googleapis.com/test/exports/story.html")
    blob = bucket.blobs["exports/story.html"]
    assert blob.calls == [("<html></html>", "text/html; charset=utf-8")]


def test_upload_html_to_gcs_without_bucket(monkeypatch):
    configure_storage(monkeypatch, bucket="")
    assert gcs_storage.upload_html_to_gcs("<p>data</p>", "story.html") is None


def test_list_gcs_exports_sorted(monkeypatch):
    configure_storage(monkeypatch, prefix="exports/")

    newer = datetime(2024, 1, 2, tzinfo=timezone.utc)
    older = datetime(2024, 1, 1, tzinfo=timezone.utc)
    blobs = [
        SimpleNamespace(
            name="exports/older.html",
            public_url="https://example.com/older",
            updated=older,
            size=120,
        ),
        SimpleNamespace(
            name="exports/newer.html",
            public_url="https://example.com/newer",
            updated=newer,
            size=140,
        ),
        SimpleNamespace(
            name="exports/ignore.txt",
            public_url="https://example.com/ignore",
            updated=newer,
            size=10,
        ),
    ]

    class StubClient:
        def __init__(self) -> None:
            self.prefix = None

        def list_blobs(self, bucket_name: str, *, prefix: str | None = None):
            assert bucket_name == "bucket"
            self.prefix = prefix
            return blobs

        def bucket(self, bucket_name: str):  # pragma: no cover - not used
            raise AssertionError("bucket() should not be called in this test")

    client = StubClient()
    monkeypatch.setattr(gcs_storage, "_get_client", StubClientFactory(client), raising=False)

    exports = gcs_storage.list_gcs_exports()

    assert [item.filename for item in exports] == ["newer.html", "older.html"]
    assert client.prefix == "exports/"
    assert exports[0].public_url == "https://example.com/newer"


def test_download_gcs_export(monkeypatch):
    configure_storage(monkeypatch, prefix="exports/")

    class StubBlob:
        def __init__(self, object_name: str) -> None:
            self.object_name = object_name

        def download_as_text(self, encoding: str = "utf-8") -> str:
            assert encoding == "utf-8"
            return "<html>story</html>"

    class StubBucket:
        def __init__(self) -> None:
            self.requested = None

        def blob(self, object_name: str) -> StubBlob:
            self.requested = object_name
            return StubBlob(object_name)

    bucket = StubBucket()

    class StubClient:
        def bucket(self, bucket_name: str) -> StubBucket:
            assert bucket_name == "bucket"
            return bucket

    monkeypatch.setattr(gcs_storage, "_get_client", StubClientFactory(StubClient()), raising=False)

    content = gcs_storage.download_gcs_export("exports/demo.html")

    assert content == "<html>story</html>"
    assert bucket.requested == "exports/demo.html"


def test_download_gcs_export_without_bucket(monkeypatch):
    configure_storage(monkeypatch, bucket="")
    assert gcs_storage.download_gcs_export("exports/missing.html") is None
