from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")


def _load_app(monkeypatch, tmp_path: Path, mode: str):
    monkeypatch.setenv("STORY_STORAGE_MODE", mode)
    monkeypatch.setattr(st, "set_page_config", lambda *args, **kwargs: None)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "HTML_EXPORT_PATH", export_dir)
    monkeypatch.setattr(app_module, "HTML_EXPORT_DIR", str(export_dir))
    return app_module


def _sample_stages():
    return [
        {
            "stage_name": "발단",
            "card_name": "카드",
            "card_prompt": "프롬프트",
            "paragraphs": ["첫 문장"],
            "image_bytes": None,
            "image_mime": "image/png",
            "image_style_name": None,
        }
    ]


def test_export_story_remote_mode(monkeypatch, tmp_path):
    app_module = _load_app(monkeypatch, tmp_path, "remote")

    upload_calls: list[str] = []

    def fake_upload(html: str, filename: str):
        upload_calls.append(filename)
        return (f"remote/{filename}", f"https://example.com/{filename}")

    monkeypatch.setattr(app_module, "upload_html_to_gcs", fake_upload)

    result = app_module.export_story_to_html(
        title="테스트",
        age="6-8",
        topic="주제",
        story_type="모험",
        stages=_sample_stages(),
        cover=None,
    )

    assert app_module.USE_REMOTE_EXPORTS is True
    assert upload_calls, "remote mode should upload to GCS"
    expected_suffix = upload_calls[0]
    assert result.gcs_object == f"remote/{expected_suffix}"
    assert result.gcs_url == f"https://example.com/{expected_suffix}"
    assert Path(result.local_path).exists()


def test_export_story_local_mode(monkeypatch, tmp_path):
    app_module = _load_app(monkeypatch, tmp_path, "local")

    def fail_upload(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("local mode must not trigger GCS uploads")

    monkeypatch.setattr(app_module, "upload_html_to_gcs", fail_upload)

    result = app_module.export_story_to_html(
        title="테스트",
        age="6-8",
        topic="주제",
        story_type="모험",
        stages=_sample_stages(),
        cover=None,
    )

    assert app_module.USE_REMOTE_EXPORTS is False
    assert result.gcs_object is None
    assert result.gcs_url is None
    assert Path(result.local_path).exists()
