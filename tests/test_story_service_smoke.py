from __future__ import annotations

from pathlib import Path

from services import story_service


def test_export_story_to_html_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(story_service, "HTML_EXPORT_PATH", tmp_path)
    monkeypatch.setattr(story_service, "HTML_EXPORT_DIR", tmp_path.name)

    stage = story_service.StagePayload(
        stage_name="발단",
        card_name="모험의 시작",
        card_prompt="용사",
        paragraphs=["첫 문장", "둘째 문장"],
        image_bytes=None,
        image_mime="image/png",
    )
    bundle = story_service.StoryBundle(
        title="테스트 동화",
        stages=[stage],
        synopsis="간단 소개",
        protagonist="용사",
        cover=None,
        story_type_name="모험",
        age="6-8",
        topic="용",
    )

    result = story_service.export_story_to_html(bundle=bundle, author="작가", use_remote_exports=False)

    exported = Path(result.local_path)
    assert exported.exists()

    html = exported.read_text(encoding="utf-8")
    assert "테스트 동화" in html
    assert "첫 문장" in html
    assert "작성자" in html
