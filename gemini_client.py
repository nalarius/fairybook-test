"""Gemini client adapters with prompt helpers and SDK wrappers."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Callable, Tuple, cast

from prompts.story import (
    STAGE_GUIDANCE as _STAGE_GUIDANCE,
    build_image_prompt_text,
    build_protagonist_prompt,
    build_story_prompt,
    build_synopsis_prompt,
    build_title_prompt,
)
from services import gemini_api
from services.gemini_api import TextGenerationResult as _TextGenerationResult

API_KEY = gemini_api.API_KEY
_MODEL = gemini_api.TEXT_MODEL
_IMAGE_MODEL = gemini_api.IMAGE_MODEL
_IMAGE_MODEL_FALLBACKS = gemini_api.IMAGE_MODEL_FALLBACKS

_STYLE_JSON_PATH = Path("illust_styles.json")
_ILLUST_STYLES_CACHE: list[dict] | None = None


def _get_genai_module():
    return gemini_api.get_genai_module()


genai = gemini_api.genai


def _extract_text_from_response(resp) -> str:
    return gemini_api.extract_text_from_response(resp)


def _strip_json_code_fence(text: str) -> str:
    """```json fences or labels 제거."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        filtered_lines = [
            line for line in cleaned.splitlines()
            if not line.strip().lower().startswith("json")
        ]
        cleaned = "\n".join(filtered_lines).strip()
    return cleaned


def _extract_first_json_object(text: str) -> str | None:
    """Best-effort extraction of the first top-level JSON object from arbitrary text."""

    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for idx, char in enumerate(text[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def _coerce_str_list(values) -> list[str]:
    """입력값을 안전한 문자열 리스트로 정규화."""

    if values is None:
        return []
    if isinstance(values, str):
        candidate = [values]
    elif isinstance(values, (tuple, set)):
        candidate = list(values)
    else:
        candidate = values if isinstance(values, list) else [values]

    cleaned: list[str] = []
    for item in candidate:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _load_illust_styles() -> list[dict]:
    """illust_styles.json에서 사용할 수 있는 스타일 목록을 반환."""

    global _ILLUST_STYLES_CACHE

    if _ILLUST_STYLES_CACHE is not None:
        return _ILLUST_STYLES_CACHE

    try:
        with _STYLE_JSON_PATH.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except FileNotFoundError:
        _ILLUST_STYLES_CACHE = []
        return _ILLUST_STYLES_CACHE
    except json.JSONDecodeError:
        _ILLUST_STYLES_CACHE = []
        return _ILLUST_STYLES_CACHE

    styles = payload.get("illust_styles") or []
    cleaned: list[dict] = []
    for item in styles:
        name = (item.get("name") or "").strip()
        style_text = (item.get("style") or "").strip()
        if not name or not style_text:
            continue
        cleaned.append({"name": name, "style": style_text})

    _ILLUST_STYLES_CACHE = cleaned
    return _ILLUST_STYLES_CACHE


def _missing_api_key_error() -> dict:
    return gemini_api.missing_api_key_error()


def _require_api_key() -> dict | None:
    return gemini_api.require_api_key()


def _generate_text_with_retry(
    prompt: str,
    *,
    attempts: int = 3,
    empty_error_message: str = "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)",
    model_factory: Callable[[str], Any] | None = None,
    parser: Callable[[str], Tuple[Any | None, dict | None]] | None = None,
) -> _TextGenerationResult:
    return gemini_api.generate_text_with_retry(
        prompt,
        attempts=attempts,
        empty_error_message=empty_error_message,
        model_factory=model_factory,
        parser=parser,
    )


def _parse_json_from_text(
    text: str,
    *,
    allow_fallback: bool = False,
) -> Tuple[dict | None, dict | None]:
    """텍스트에서 JSON 객체를 파싱한다."""

    cleaned = _strip_json_code_fence(text)
    try:
        return json.loads(cleaned), None
    except json.JSONDecodeError as exc:
        if not allow_fallback:
            return None, {"error": f"JSONDecodeError: {exc}"}

        fallback_payload = _extract_first_json_object(text)
        if fallback_payload is None:
            return None, {"error": f"JSONDecodeError: {exc}"}

        try:
            return json.loads(fallback_payload), None
        except json.JSONDecodeError as exc_inner:
            return None, {"error": f"JSONDecodeError: {exc_inner}"}


def build_image_prompt(
    story: dict,
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    story_card_name: str | None = None,
    stage_name: str | None = None,
    style_override: dict | None = None,
    is_character_sheet: bool = False,
    use_reference_image: bool = False,
    protagonist_text: str | None = None,
) -> dict:
    """이야기와 스타일 정보를 바탕으로 이미지 생성 프롬프트를 구성."""

    api_error = _require_api_key()
    if api_error:
        return api_error

    styles = _load_illust_styles()
    if not styles:
        return {"error": "illust_styles.json에서 사용할 수 있는 스타일을 찾지 못했습니다."}

    style_choice = None
    if style_override:
        name = (style_override.get("name") if isinstance(style_override, dict) else None) or ""
        style_text_override = (style_override.get("style") if isinstance(style_override, dict) else None) or ""
        if name and style_text_override:
            style_choice = {"name": name, "style": style_text_override}

    if style_choice is None:
        style_choice = random.choice(styles)

    style_name = style_choice.get("name", "Unnamed Style")
    style_text = style_choice.get("style", "")

    title = (story.get("title") or "").strip() if isinstance(story, dict) else ""
    paragraphs_raw = story.get("paragraphs") if isinstance(story, dict) else None
    paragraphs = [str(p).strip() for p in (paragraphs_raw or []) if str(p).strip()]
    if not paragraphs:
        return {"error": "story 본문이 비어 있어 이미지 프롬프트를 만들 수 없습니다."}

    directive = build_image_prompt_text(
        story_title=title,
        story_paragraphs=paragraphs,
        age=age,
        topic=topic,
        story_type_name=story_type_name,
        story_card_name=story_card_name,
        stage_name=stage_name,
        style_name=style_name,
        style_text=style_text,
        is_character_sheet=is_character_sheet,
        use_reference_image=use_reference_image,
        protagonist_text=protagonist_text,
    )

    def _prompt_parser(raw_text: str) -> Tuple[str | None, dict | None]:
        cleaned = (raw_text or "").strip()
        if cleaned.startswith("```"):
            stripped = cleaned.strip("`")
            cleaned_lines = [ln for ln in stripped.splitlines() if not ln.strip().lower().startswith("prompt")]
            cleaned = " ".join(line.strip() for line in cleaned_lines if line.strip()).strip()
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return None, {"error": "Image prompt generation failed."}
        return cleaned, None

    result = _generate_text_with_retry(
        directive,
        empty_error_message="Image prompt generation failed.",
        parser=_prompt_parser,
    )
    if not result.ok:
        return result.error or {"error": "Image prompt generation failed."}

    return {
        "prompt": cast(str, result.payload),
        "style_name": style_name,
        "style_text": style_text,
    }


def generate_title_with_gemini(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    *,
    synopsis: str | None = None,
    protagonist: str | None = None,
) -> dict:
    """Gemini로 동화 제목을 생성."""

    api_error = _require_api_key()
    if api_error:
        return api_error

    prompt = build_title_prompt(
        age=age,
        topic=topic,
        story_type_name=story_type_name,
        story_type_prompt=story_type_prompt,
        synopsis_text=synopsis,
        protagonist_text=protagonist,
    )

    def _title_parser(raw_text: str) -> Tuple[dict | None, dict | None]:
        data, parse_error = _parse_json_from_text(raw_text, allow_fallback=False)
        if parse_error:
            return None, parse_error
        title_value = (data.get("title") or "").strip()
        if not title_value:
            return None, {"error": "제목을 찾지 못했습니다.", "raw": data}
        return {"title": title_value}, None

    result = _generate_text_with_retry(
        prompt,
        parser=_title_parser,
    )
    if not result.ok:
        return result.error or {"error": "제목 생성에 실패했습니다."}

    return cast(dict[str, str], result.payload)


def generate_synopsis_with_gemini(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
) -> dict:
    """Gemini로 간단한 시놉시스를 생성."""

    api_error = _require_api_key()
    if api_error:
        return api_error

    prompt = build_synopsis_prompt(
        age=age,
        topic=topic,
        story_type_name=story_type_name,
        story_type_prompt=story_type_prompt,
    )
    result = _generate_text_with_retry(prompt)
    if not result.ok:
        return result.error or {"error": "시놉시스 생성에 실패했습니다."}

    synopsis_text = cast(str, result.payload)
    if not synopsis_text:
        return {"error": "시놉시스를 찾지 못했습니다."}

    return {"synopsis": synopsis_text}


def generate_protagonist_with_gemini(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    synopsis_text: str | None,
) -> dict:
    """Gemini로 주인공 상세 설정을 생성."""

    api_error = _require_api_key()
    if api_error:
        return api_error

    prompt = build_protagonist_prompt(
        age=age,
        topic=topic,
        story_type_name=story_type_name,
        story_type_prompt=story_type_prompt,
        synopsis_text=synopsis_text,
    )
    result = _generate_text_with_retry(prompt)
    if not result.ok:
        return result.error or {"error": "주인공 설정 생성에 실패했습니다."}

    protagonist_text = cast(str, result.payload)
    if not protagonist_text:
        return {"error": "주인공 설정을 찾지 못했습니다."}

    return {"description": protagonist_text}


def build_character_image_prompt(
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    synopsis_text: str | None,
    protagonist_text: str | None,
    style_override: dict | None = None,
) -> dict:
    """주인공 정보를 바탕으로 설정화 이미지 프롬프트를 생성."""

    if not protagonist_text:
        return {"error": "주인공 정보가 없어 이미지 프롬프트를 만들 수 없습니다."}

    paragraphs = []
    if synopsis_text:
        paragraphs.append(f"Synopsis: {synopsis_text}")
    paragraphs.append(f"Protagonist: {protagonist_text}")

    story_payload = {
        "title": "Character Sheet",
        "paragraphs": paragraphs,
    }

    return build_image_prompt(
        story_payload,
        age=age,
        topic=topic,
        story_type_name=story_type_name,
        story_card_name="Character Blueprint",
        stage_name="캐릭터 설정화",
        style_override=style_override,
        is_character_sheet=True,
        protagonist_text=protagonist_text,
    )


def generate_story_with_gemini(
    age: str,
    topic: str | None,
    *,
    title: str,
    story_type_name: str,
    stage_name: str,
    stage_index: int,
    total_stages: int,
    story_card_name: str,
    story_card_prompt: str,
    previous_sections: list[dict] | None = None,
    synopsis_text: str | None = None,
    protagonist_text: str | None = None,
) -> dict:
    """Gemini로 단계별 동화를 생성해 {title, paragraphs[]} dict를 반환."""

    api_error = _require_api_key()
    if api_error:
        return api_error

    prompt = build_story_prompt(
        age=age,
        topic=topic,
        title=title,
        story_type_name=story_type_name,
        stage_name=stage_name,
        stage_index=stage_index,
        total_stages=total_stages,
        story_card_name=story_card_name,
        story_card_prompt=story_card_prompt,
        previous_sections=previous_sections,
        synopsis_text=synopsis_text,
        protagonist_text=protagonist_text,
    )

    def _story_parser(raw_text: str) -> Tuple[dict | None, dict | None]:
        data, parse_error = _parse_json_from_text(raw_text, allow_fallback=True)
        if parse_error:
            return None, parse_error

        paragraphs = data.get("paragraphs") or []
        if not isinstance(paragraphs, list) or not paragraphs:
            return None, {"error": "반환 JSON 형식이 예상과 다릅니다.", "raw": data}

        cleaned_paragraphs = [str(p).strip() for p in paragraphs if str(p).strip()]
        if not cleaned_paragraphs:
            return None, {"error": "본문 단락을 찾지 못했습니다.", "raw": data}

        final_title = (data.get("title") or title or "").strip() or title
        return {"title": final_title, "paragraphs": cleaned_paragraphs}, None

    result = _generate_text_with_retry(
        prompt,
        parser=_story_parser,
    )
    if not result.ok:
        return result.error or {"error": "동화 생성에 실패했습니다."}

    return cast(dict[str, Any], result.payload)


def generate_image_with_gemini(prompt: str, *, image_input: bytes | None = None) -> dict:
    """Gemini/Imagen 모델로 prompt 기반 삽화를 생성."""

    return gemini_api.generate_image(prompt, image_input=image_input)


__all__ = [
    "API_KEY",
    "_MODEL",
    "_IMAGE_MODEL",
    "_IMAGE_MODEL_FALLBACKS",
    "_STAGE_GUIDANCE",
    "_extract_text_from_response",
    "_strip_json_code_fence",
    "_extract_first_json_object",
    "_coerce_str_list",
    "_load_illust_styles",
    "_missing_api_key_error",
    "_require_api_key",
    "_generate_text_with_retry",
    "_parse_json_from_text",
    "build_image_prompt",
    "generate_title_with_gemini",
    "generate_synopsis_with_gemini",
    "generate_protagonist_with_gemini",
    "build_character_image_prompt",
    "generate_story_with_gemini",
    "generate_image_with_gemini",
    "genai",
    "_get_genai_module",
]

