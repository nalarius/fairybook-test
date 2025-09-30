from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.story_service import (
    HTML_EXPORT_PATH,
    StagePayload,
    StoryBundle,
    export_story_to_html,
)


@pytest.fixture(autouse=True)
def _patch_export_path(monkeypatch, tmp_path: Path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("services.story_service.HTML_EXPORT_PATH", export_dir, raising=False)
    return export_dir


@pytest.fixture
def sample_bundle() -> StoryBundle:
    stage = StagePayload(
        stage_name="발단",
        card_name="카드",
        card_prompt="프롬프트",
        paragraphs=["첫 문장"],
        image_bytes=None,
        image_mime="image/png",
        image_style_name=None,
    )
    return StoryBundle(
        title="테스트",
        stages=[stage],
        synopsis=None,
        protagonist=None,
        cover=None,
        story_type_name="모험",
        age="6-8",
        topic="주제",
    )


def test_export_story_remote_mode(monkeypatch, sample_bundle):
    upload_calls: list[str] = []

    def fake_upload(html: str, filename: str):
        upload_calls.append(filename)
        return (f"remote/{filename}", f"https://example.com/{filename}")

    monkeypatch.setattr("services.story_service.upload_html_to_gcs", fake_upload)

    result = export_story_to_html(
        bundle=sample_bundle,
        author=None,
        use_remote_exports=True,
    )

    assert upload_calls, "remote mode should upload to GCS"
    expected_suffix = upload_calls[0]
    assert result.gcs_object == f"remote/{expected_suffix}"
    assert result.gcs_url == f"https://example.com/{expected_suffix}"
    assert Path(result.local_path).exists()


def test_export_story_local_mode(monkeypatch, sample_bundle):
    def fail_upload(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("local mode must not trigger GCS uploads")

    monkeypatch.setattr("services.story_service.upload_html_to_gcs", fail_upload)

    result = export_story_to_html(
        bundle=sample_bundle,
        author="테스터",
        use_remote_exports=False,
    )

    assert result.gcs_object is None
    assert result.gcs_url is None
    assert Path(result.local_path).exists()
