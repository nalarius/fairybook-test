# gemini_client.py
# ── 0) 로그 억제: gRPC/absl 메시지를 조용히 ──────────────────────────
import base64
import io
import os
import random
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Tuple, cast

from PIL import Image

os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_TRACE"] = ""

try:
    from absl import logging as absl_logging
    absl_logging.set_verbosity(absl_logging.ERROR)
except Exception:
    pass

# ── 1) .env에서 API 키 로드 ─────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── 2) Gemini 설정 ──────────────────────────────────────────────────
import json
_GENAI_MODULE: Any | None = None
_GENAI_CONFIGURED = False
genai: Any = SimpleNamespace(GenerativeModel=None)


def _get_genai_module():
    """Lazily import and configure the google.generativeai SDK."""
    global _GENAI_MODULE, _GENAI_CONFIGURED, genai

    if _GENAI_MODULE is None:
        if getattr(genai, "GenerativeModel", None) is not None:
            _GENAI_MODULE = genai
        else:
            import google.generativeai as genai_mod  # type: ignore

            _GENAI_MODULE = genai_mod
            genai = genai_mod

    if not _GENAI_CONFIGURED:
        if API_KEY and hasattr(_GENAI_MODULE, "configure"):
            _GENAI_MODULE.configure(api_key=API_KEY)
        _GENAI_CONFIGURED = True

    return _GENAI_MODULE

_MODEL_ENV = (os.getenv("GEMINI_TEXT_MODEL") or "").strip()
_MODEL = _MODEL_ENV or "models/gemini-2.5-flash"
_IMAGE_MODEL_ENV = (os.getenv("GEMINI_IMAGE_MODEL") or "").strip()
_IMAGE_MODEL = _IMAGE_MODEL_ENV or "gemini-1.5-flash"
_IMAGE_MODEL_FALLBACKS = ()
_STYLE_JSON_PATH = Path("illust_styles.json")

_ILLUST_STYLES_CACHE: list[dict] | None = None


@dataclass(frozen=True)
class _TextGenerationResult:
    """Internal helper structure for Gemini 텍스트 호출 결과."""

    ok: bool
    payload: Any | None = None
    error: dict | None = None


def _missing_api_key_error() -> dict:
    return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

_STAGE_GUIDANCE = {
    "발단": "주인공과 배경, 출발 계기를 선명하게 보여주고 모험의 씨앗을 심어 주세요. 따뜻함과 호기심이 함께 느껴지도록 합니다.",
    "전개": "주요 갈등과 사건을 키우며 인물들의 선택을 드러내세요. 긴장감과 숨 돌릴 따뜻한 순간이 번갈아 나오도록 합니다.",
    "위기": "가장 큰 위기와 감정의 파고를 그려주세요. 위험과 두려움 속에서도 서로의 믿음이나 재치가 빛날 틈을 남깁니다.",
    "절정": "결정적인 행동과 극적인 전환을 보여주세요. 장엄하거나 아슬아슬한 분위기 속에서 감정이 폭발하도록 합니다.",
    "결말": "사건의 여파를 정리하며 여운을 남기세요. 밝거나 씁쓸한 결말 모두 가능하며, 다음 상상을 부르는 여백을 둡니다.",
}


def _extract_text_from_response(resp) -> str:
    """Gemini SDK 응답에서 텍스트 본문을 꺼낸다."""
    if hasattr(resp, "text") and resp.text:
        return str(resp.text)

    try:
        candidates = getattr(resp, "candidates", []) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) if content else None
            if parts:
                return " ".join([
                    getattr(part, "text", "") for part in parts if getattr(part, "text", "")
                ])
    except Exception:
        return ""

    return ""


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


def _require_api_key() -> dict | None:
    """API 키가 없으면 에러 dict 반환, 있으면 None."""
    return None if API_KEY else _missing_api_key_error()


def _generate_text_with_retry(
    prompt: str,
    *,
    attempts: int = 3,
    empty_error_message: str = "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)",
    model_factory: Callable[[str], Any] | None = None,
    parser: Callable[[str], Tuple[Any | None, dict | None]] | None = None,
) -> _TextGenerationResult:
    """공통 Gemini 텍스트 호출 및 파싱 로직."""

    if attempts < 1:
        attempts = 1

    genai_mod = None if model_factory else _get_genai_module()
    factory = model_factory or genai_mod.GenerativeModel
    last_error: dict | None = None

    for attempt in range(1, attempts + 1):
        try:
            model = factory(_MODEL)
            response = model.generate_content(prompt)
        except Exception as exc:
            last_error = {"error": f"{type(exc).__name__}: {exc}", "attempt": attempt}
            continue

        text = _extract_text_from_response(response)
        text = (text or "").strip()
        if not text:
            last_error = {"error": empty_error_message, "attempt": attempt}
            continue

        if parser:
            parsed_payload, parse_error = parser(text)
            if parse_error is not None:
                last_error = {**parse_error, "attempt": attempt}
                continue
            return _TextGenerationResult(ok=True, payload=parsed_payload)

        return _TextGenerationResult(ok=True, payload=text)

    if last_error is None:
        last_error = {"error": "텍스트 생성에 실패했습니다.", "attempts": attempts}
    else:
        last_error.setdefault("attempts", attempts)
    return _TextGenerationResult(ok=False, error=last_error)


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

def _build_title_prompt(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    synopsis_text: str | None = None,
    protagonist_text: str | None = None,
) -> str:
    topic_clean = (topic or "").strip()
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미생성)"
    protagonist_block = (protagonist_text or "").strip() or "(주인공 설정 미생성)"

    return f"""당신은 어린이를 위한 동화 작가입니다.
입력으로 나이대, 주제, 이야기 유형, 시놉시스, 주인공 정보가 주어집니다.
이 정보를 활용하여 동화의 분위기와 핵심 갈등을 담은 **인상적인 한국어 제목**을 하나 만들어 주세요.

- **반드시 하나의 최종 제목만 생성해야 합니다.** 두 개 이상의 제목을 이어서 붙이지 마세요.
- 밝은 모험과 서늘한 긴장이 교차할 수 있음을 반영하고, 따뜻한 장면이나 유머의 여지도 남겨두세요.
- 결말을 특정 방향으로 단정 짓지 말고, 행복한 끝과 씁쓸한 끝 모두 가능하다는 여운을 살려주세요.
- 감정을 단조롭게 만들지 말고 장면이 떠오르는 단어로 분위기를 암시하세요.
- 한국 독자가 익숙한 자연스러운 표현을 사용하고, 문장은 간결하면서도 임팩트 있게 구성하세요.
- 제목은 25자 이내로 작성하며 구두점을 사용하지 않습니다.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
- 시놉시스: {synopsis_block}
- 주인공 설명: {protagonist_block}

[출력 형식]
{{
  "title": "제목"
}}
"""


def _build_synopsis_prompt(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
) -> str:
    topic_clean = (topic or "").strip()
    return f"""당신은 어린이 그림책 기획을 맡은 시니어 편집자입니다. 입력으로 나이대, 주제, 이야기 유형 설명이 주어집니다. 이 정보를 토대로 동화의 토대가 되는 간단한 시놉시스를 작성하세요.
- 밝은 모험과 서늘한 긴장이 공존하되, 숨 돌릴 수 있는 따뜻한 순간도 포함하세요.
- 결말을 특정 방향으로 고정하지 말고 열린 여운을 남기세요.
- **결과는 반드시 한 문단의 평문으로만 작성하고, 절대로 불릿, 번호 목록, JSON 형식 등을 사용하지 마세요.**
- 문장 수는 3~5문장, 자연스러운 한국어 흐름으로 구성하세요.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
"""


def _build_protagonist_prompt(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    synopsis_text: str | None,
) -> str:
    topic_clean = (topic or "").strip()
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미생성)"
    return f"""당신은 어린이 동화의 캐릭터 디자이너입니다. 입력으로 한 동화의 나이대, 주제, 이야기 유형, 간단한 시놉시스가 주어집니다. 이 동화의 주인공의 상세 설정을 **한 문단의 평문으로만** 작성하세요.

- 주인공의 이름, 정체성, 성격, 목표, 외형적 특징, 상징적인 소품 등을 자연스럽게 엮어 하나의 이야기처럼 묘사합니다.
- 주인공이 겪는 위기와 성장 동기를 분명히 제시하되, 한쪽 감정에 치우치지 마세요.
- 밝은 모험과 서늘한 긴장이 공존하도록 성격과 행동을 설계하고, 숨 돌릴 따뜻한 면모나 익살스러운 특징도 드러내세요.
- 외형·복장·상징 소품을 구체적으로 묘사하되 잔혹한 표현은 피하세요.
- **결과는 반드시 한 문단의 평문으로만 작성하고, 절대로 불릿, 번호 목록, JSON 형식 등을 사용하지 마세요.**
- 문장은 3~5개 사이의 자연스러운 한국어로 구성합니다.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
- 시놉시스: {synopsis_block}
"""


def _build_story_prompt(
    *,
    age: str,
    topic: str | None,
    title: str,
    story_type_name: str,
    stage_name: str,
    stage_index: int,
    total_stages: int,
    story_card_name: str,
    story_card_prompt: str,
    previous_sections: list[dict] | None,
    synopsis_text: str | None = None,
    protagonist_text: str | None = None,
) -> str:
    topic_clean = (topic or "").strip()
    safe_title = json.dumps(title.strip(), ensure_ascii=False) if title else '"동화"'
    stage_number = stage_index + 1
    total_count = max(total_stages, stage_number)
    stage_label = stage_name or f"{stage_number}단계"
    stage_focus = _STAGE_GUIDANCE.get(stage_name, "이번 단계의 극적 역할을 명확하게 드러내며 사건과 감정을 전개하세요.")

    previous_sections = previous_sections or []
    summary_lines: list[str] = []
    for item in previous_sections:
        label = item.get("stage") or item.get("stage_name") or f"단계 {len(summary_lines) + 1}"
        card_name = item.get("card_name") or item.get("card")
        paragraphs = item.get("paragraphs") or []
        merged = " ".join(str(p).strip() for p in paragraphs if str(p).strip())
        merged = merged[:600] if merged else "(간단한 요약이 없습니다)"
        if card_name:
            label = f"{label} ({card_name})"
        summary_lines.append(f"{label}: {merged}")

    if summary_lines:
        previous_block = "\n".join(f"- {line}" for line in summary_lines)
    else:
        previous_block = "- 아직 작성된 단계가 없습니다."

    card_prompt_clean = (story_card_prompt or "").strip() or "(설명 없음)"
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미제공)"
    protagonist_block = (protagonist_text or "").strip() or "(주인공 미제공)"

    return f"""당신은 어린이를 위한 연속 동화 작가입니다.
이 동화는 총 {total_count}단계 구조(발단-전개-위기-절정-결말)로 진행되며, 지금은 {stage_number}단계 "{stage_label}"을 작성합니다.
앞선 단계들의 분위기와 인과를 이어가면서, 이번 단계만의 극적 역할을 분명히 하세요.

[전체 이야기 설정]
- 시놉시스: {synopsis_block}
- 주인공: {protagonist_block}

[이전 단계 요약]
{previous_block}

[이번 단계 카드]
- 카드 이름: {story_card_name}
- 카드 설명: {card_prompt_clean}

[작성 지침]
- {stage_focus}
- **주인공 설정과 시놉시스를 충실히 반영하여** 이전 단계와 자연스럽게 이어지도록 사건과 감정의 흐름을 조율하세요.
- 감정과 상황은 인물의 행동, 대사, 표정, 호흡, 몸짓, 주변 환경 묘사로 보여 주고, 단정적인 설명은 줄이세요. 필요하면 내적 독백과 미세한 감각 변화를 통해 심리를 드러내세요.
- 밝은 순간과 서늘한 긴장감이 공존하도록 하고, 모험 속 위기와 숨 돌릴 유머나 따뜻함을 함께 담으세요.
- 반전이나 정체성 전환은 한국어식 표현이나 대사로 드러내고, 영어식 문장 구조를 사용하지 마세요.
- 시각·청각·후각·촉각·미각 등 오감을 활용해 장면의 공기와 질감을 생생하게 전달하세요.
- 문장은 간결하고 임팩트 있게 구성하되, 자연스럽고 인간적인 한국어 리듬을 유지하세요.
- 결말을 강요하지 말고 다양한 감정의 선택지를 열어 두되, 이번 단계가 전체 서사의 탄탄한 디딤돌이 되도록 하세요.
- 나이대에 맞는 어휘와 리듬을 사용하고, 주제를 인물의 행동과 상징에 자연스럽게 녹여 주세요.
- 장면 묘사, 인물의 감정, 대화를 균형 있게 배치해 아이가 장면을 선명하게 상상할 수 있도록 하세요.

[출력 형식]
{{
  "title": {safe_title},
  "paragraphs": ["첫 번째 단락", "두 번째 단락"]
}}
- JSON 이외의 설명이나 주석을 붙이지 마세요.
- "paragraphs" 리스트는 정확히 2개의 단락을 담습니다. 각 단락은 2~3문장으로 작성해 리듬감 있게 전개하세요.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 제목: {title.strip()}
- 이야기 유형: {story_type_name}
- 현재 단계: {stage_label} (총 {total_count}단계 중 {stage_number}단계)
- 이야기 카드 이름: {story_card_name}
- 이야기 카드 설명: {card_prompt_clean}
"""

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
    style_fragments = [fragment.strip() for fragment in style_text.split(",") if fragment.strip()]
    traits_block = "\n".join(f"- {fragment}" for fragment in style_fragments) if style_fragments else "- Warm, friendly picture book aesthetic"

    title = (story.get("title") or "").strip() if isinstance(story, dict) else ""
    paragraphs_raw = story.get("paragraphs") if isinstance(story, dict) else None
    paragraphs = [str(p).strip() for p in (paragraphs_raw or []) if str(p).strip()]
    if not paragraphs:
        return {"error": "story 본문이 비어 있어 이미지 프롬프트를 만들 수 없습니다."}

    topic_text = (topic or "").strip() or "(빈칸)"
    summary = " ".join(paragraphs)
    summary = summary[:1500]

    character_sheet_directive = ""
    if is_character_sheet:
        character_sheet_directive = """
- **This is a character sheet.** The image must feature the main character only.
- The background must be a solid, plain, clean white background.
- The character should be in a neutral, full-body pose.
- Do not include any shadows, text, or other elements. Just the character.
"""

    reference_image_directive = ""
    if use_reference_image:
        reference_image_directive = (
            "\n- **The provided reference image depicts the story's protagonist. Center the cover around this exact character.**"
            "\n- **Crucially, the protagonist described below MUST strictly match the provided character reference image.** Depict the character as shown in the reference image, adapting their pose, wardrobe, and features faithfully while placing them in the new scene described in the summary."
        )

    protagonist_block = f"\n- Protagonist Description: {protagonist_text}" if protagonist_text else ""

    directive = f"""You are an art director and text-to-image prompt engineer for a children's picture book. Analyze the given story plot and style references to write a prompt for generating **a single illustration** in English. Faithfully capture the unique mood of the style to allow young readers to experience new emotions.

[Story]
- Title: {title or "(Untitled)"}
- Age Group: {age}
- Topic: {topic_text}
- Story Type: {story_type_name}
- Narrative Card: {story_card_name or "(Not selected)"}
- Stage: {stage_name or "(Not specified)"}
- Summary: {summary}{protagonist_block}

[Style Reference]
- Illustrator: {style_name}
- Descriptor: {style_text}
- Style Traits:\n{traits_block}

[Requirements]
- The final output must be a single paragraph of a pure English prompt (no bullets or explanations).
- It must include the phrase "in the style of {style_name}".
- It must incorporate the expressions listed in the Style Traits above, connecting them naturally with the scene description.
- Describe the main characters, key events, background, emotions, lighting, and color palette in detail.
- Prioritize recreating the mood and emotion required by the style; do not force it to be cute or safe.
- Include "without text, typography, signature, or watermark" in the generation prompt to ensure no text, logos, or signs appear.{character_sheet_directive}{reference_image_directive}
"""

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

    prompt = _build_title_prompt(
        age,
        topic,
        story_type_name,
        story_type_prompt,
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

    prompt = _build_synopsis_prompt(age, topic, story_type_name, story_type_prompt)
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

    prompt = _build_protagonist_prompt(age, topic, story_type_name, story_type_prompt, synopsis_text)
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
    """
    Gemini로 단계별 동화를 생성해 {title, paragraphs[]} dict를 반환.
    실패 시 {"error": "..."} 반환.
    """
    api_error = _require_api_key()
    if api_error:
        return api_error

    prompt = _build_story_prompt(
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

def _coerce_bytes(value):
    """다양한 SDK 응답 형식을 안전하게 bytes로 변환."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=False)
        except Exception:
            try:
                return base64.b64decode(value.encode("utf-8"))
            except Exception:
                return value.encode("utf-8")
    data_attr = getattr(value, "data", None)
    if data_attr is not None and data_attr is not value:
        return _coerce_bytes(data_attr)
    if hasattr(value, "tobytes"):
        try:
            return value.tobytes()
        except Exception:
            return None
    return None


def _iter_image_models():
    """환경 변수와 권장 기본값을 순회하며 중복 없이 모델 후보를 제공."""
    seen = set()
    for name in (_IMAGE_MODEL, *_IMAGE_MODEL_FALLBACKS):
        if not name or name in seen:
            continue
        seen.add(name)
        yield name


def _instantiate_image_model(model_name: str):
    """SDK 버전에 따라 적합한 이미지 모델 인스턴스를 생성."""
    genai_mod = _get_genai_module()
    return genai_mod.GenerativeModel(model_name)


def _extract_image_from_response(resp):
    """Google Generative AI 응답 객체에서 이미지와 MIME 타입 추출."""
    try:
        if isinstance(resp, (bytes, str)):
            return _coerce_bytes(resp), "image/png"

        candidates = getattr(resp, "candidates", [])
        for cand in candidates:
            content = getattr(cand, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", [])
            for part in parts:
                blob = getattr(part, "inline_data", None)
                if blob:
                    mime = getattr(blob, "mime_type", "image/png")
                    data = getattr(blob, "data", None)
                    if data:
                        return _coerce_bytes(data), mime
    except Exception:
        pass
    return None, None


def generate_image_with_gemini(prompt: str, *, image_input: bytes | None = None) -> dict:
    """Gemini/Imagen 모델로 prompt 기반 삽화를 생성."""
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    last_error: dict | None = None

    for attempt in range(1, 4):
        model = None
        model_name = None
        init_errors = []

        for candidate in _iter_image_models():
            try:
                model = _instantiate_image_model(candidate)
                model_name = candidate
                break
            except Exception as exc:
                init_errors.append((candidate, exc))

        if model is None:
            detail = "; ".join(
                f"{name}: {type(exc).__name__} — {exc}" for name, exc in init_errors
            )
            if not detail:
                detail = "모델 후보를 찾지 못했습니다."
            last_error = {"error": f"이미지 모델 초기화 실패 — {detail}", "attempt": attempt}
            continue

        response = None
        last_exc = None

        try:
            content = [prompt]
            if image_input:
                img = Image.open(io.BytesIO(image_input))
                content.append(img)
            response = model.generate_content(content)
        except Exception as exc:
            last_exc = exc

        if response is None:
            if last_exc is None:
                last_error = {"error": "이미지 응답을 생성하지 못했습니다.", "attempt": attempt}
            else:
                detail = f"{type(last_exc).__name__}: {last_exc}"
                if "NotFound" in detail or "404" in detail:
                    detail += " — 사용 가능한 이미지 모델 이름을 ListModels로 확인하거나 GEMINI_IMAGE_MODEL 환경 변수를 설정해 주세요."
                if model_name:
                    detail = f"[{model_name}] {detail}"
                last_error = {"error": detail, "attempt": attempt}
            continue

        image_bytes, mime_type = _extract_image_from_response(response)
        if not image_bytes:
            error_details = getattr(response, "prompt_feedback", "Unknown error")
            last_error = {"error": f"모델이 이미지 데이터를 반환하지 않았습니다: {error_details}", "attempt": attempt}
            continue

        return {"bytes": image_bytes, "mime_type": mime_type or "image/png"}

    if last_error is None:
        last_error = {"error": "이미지 생성에 실패했습니다."}
    last_error.setdefault("attempts", 3)
    return last_error
