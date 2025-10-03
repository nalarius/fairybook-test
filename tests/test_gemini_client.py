import json
from types import SimpleNamespace

import pytest

import gemini_client
from services import gemini_api as gemini_api_service


class DummyResponse(SimpleNamespace):
    pass


def test_extract_text_from_response_prefers_text():
    resp = DummyResponse(text="hello world")
    assert gemini_client._extract_text_from_response(resp) == "hello world"


def test_extract_text_from_response_candidates_fallback():
    part1 = SimpleNamespace(text="first")
    part2 = SimpleNamespace(text="second")
    content = SimpleNamespace(parts=[part1, part2])
    candidate = SimpleNamespace(content=content)
    resp = DummyResponse(candidates=[candidate])
    assert gemini_client._extract_text_from_response(resp) == "first second"


def test_strip_json_code_fence_removes_markers():
    payload = "```json\n{\"key\": 1}\n```"
    assert gemini_client._strip_json_code_fence(payload) == '{"key": 1}'


def test_extract_first_json_object_from_mixed_text():
    text = "prefix ignored {\"title\": \"Story\", \"paragraphs\": []} trailing text"
    assert gemini_client._extract_first_json_object(text) == '{"title": "Story", "paragraphs": []}'


def test_coerce_str_list_filters_and_strips():
    result = gemini_client._coerce_str_list(["  apple ", None, 42])
    assert result == ["apple", "42"]


def test_load_illust_styles_trims_and_caches(monkeypatch, tmp_path):
    styles_path = tmp_path / "styles.json"
    styles_path.write_text(
        json.dumps(
            {
                "illust_styles": [
                    {"name": "  Soft Brush ", "style": " dreamy pastel "},
                    {"name": "", "style": ""},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(gemini_client, "_STYLE_JSON_PATH", styles_path)
    monkeypatch.setattr(gemini_client, "_ILLUST_STYLES_CACHE", None)

    first = gemini_client._load_illust_styles()
    assert first == [{"name": "Soft Brush", "style": "dreamy pastel"}]

    # 파일 내용을 바꿔도 캐시가 유지되는지 확인
    styles_path.write_text(json.dumps({"illust_styles": []}), encoding="utf-8")
    second = gemini_client._load_illust_styles()
    assert second == first


def test_generate_title_with_gemini_parses_response(monkeypatch):
    monkeypatch.setattr(gemini_client, "API_KEY", "test-key")
    monkeypatch.setattr(gemini_api_service, "API_KEY", "test-key")

    captured = {}

    class DummyModel:
        def __init__(self, model_name):
            captured["model_name"] = model_name

        def generate_content(self, prompt):
            captured["prompt"] = prompt
            return DummyResponse(text=json.dumps({"title": "노을 숲 모험"}, ensure_ascii=False))

    monkeypatch.setattr(gemini_client.genai, "GenerativeModel", lambda name: DummyModel(name))

    result = gemini_client.generate_title_with_gemini(
        "6-8",
        "별빛",
        "모험",
        "이야기 유형 설명",
        synopsis="이야기 요약",
        protagonist="용감한 주인공",
    )

    assert result == {"title": "노을 숲 모험"}
    assert captured["model_name"] == gemini_client._MODEL
    assert "나이대: 6-8" in captured["prompt"]


def test_generate_story_with_gemini_parses_json_fallback(monkeypatch):
    monkeypatch.setattr(gemini_client, "API_KEY", "test-key")
    monkeypatch.setattr(gemini_api_service, "API_KEY", "test-key")

    story_payload = '{"title": "바람의 모험", "paragraphs": [" 첫 장면 ", " 둘째 장면 "]}'
    response_text = f"서론 {story_payload} 결론"

    class DummyModel:
        def __init__(self, _model_name):
            pass

        def generate_content(self, prompt):
            # 요청 프롬프트가 단계 정보를 포함하는지 확인
            assert "총 5단계" in prompt
            return DummyResponse(text=response_text)

    monkeypatch.setattr(gemini_client.genai, "GenerativeModel", lambda name: DummyModel(name))

    result = gemini_client.generate_story_with_gemini(
        age="6-8",
        topic="바람",
        title="임시 제목",
        story_type_name="모험",
        stage_name="발단",
        stage_index=0,
        total_stages=5,
        story_card_name="폭풍 카드",
        story_card_prompt="작은 폭풍이 다가온다",
        previous_sections=[{"stage": "프롤로그", "card_name": "빛", "paragraphs": ["도입부"]}],
        synopsis_text="시놉시스",
        protagonist_text="주인공",
    )

    assert result["title"] == "바람의 모험"
    assert result["paragraphs"] == ["첫 장면", "둘째 장면"]


def test_build_image_prompt_returns_single_prompt(monkeypatch):
    monkeypatch.setattr(gemini_client, "API_KEY", "test-key")
    monkeypatch.setattr(gemini_api_service, "API_KEY", "test-key")
    monkeypatch.setattr(gemini_client, "_ILLUST_STYLES_CACHE", None)
    monkeypatch.setattr(gemini_client, "_load_illust_styles", lambda: [{"name": "Fallback", "style": "soft"}])

    class DummyModel:
        def __init__(self, _model_name):
            pass

        def generate_content(self, _prompt):
            return DummyResponse(text="A vivid scene in the style of Magic Painter without text, typography, signature, or watermark")

    monkeypatch.setattr(gemini_client.genai, "GenerativeModel", lambda name: DummyModel(name))

    story = {"title": "숲", "paragraphs": ["첫 장면", "둘째 장면"]}
    result = gemini_client.build_image_prompt(
        story,
        age="6-8",
        topic="숲",
        story_type_name="모험",
        story_card_name="발견",
        stage_name="발단",
        style_override={"name": "Magic Painter", "style": "bold colors"},
        protagonist_text="용감한 아이",
    )

    assert result["style_name"] == "Magic Painter"
    assert "in the style of Magic Painter" in result["prompt"]
    assert "without text, typography, signature, or watermark" in result["prompt"]


def test_build_character_image_prompt_requires_protagonist():
    result = gemini_client.build_character_image_prompt(
        age="6-8",
        topic="숲",
        story_type_name="모험",
        synopsis_text="시놉시스",
        protagonist_text=None,
    )
    assert result == {"error": "주인공 정보가 없어 이미지 프롬프트를 만들 수 없습니다."}
