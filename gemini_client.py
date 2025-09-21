# gemini_client.py
# ── 0) 로그 억제: gRPC/absl 메시지를 조용히 ──────────────────────────
import base64
import os
import random
from pathlib import Path
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
import google.generativeai as genai

if API_KEY:
    genai.configure(api_key=API_KEY)
else:
    # 키가 없어도 import 에러 없이 함수 호출 시 에러 메시지로 안내
    pass

_MODEL = "gemini-1.5-flash"  # 속도/비용 유리(샘플용)
_IMAGE_MODEL_ENV = (os.getenv("GEMINI_IMAGE_MODEL") or "").strip()
_IMAGE_MODEL = _IMAGE_MODEL_ENV or "imagen-3.0-generate-001"  # 기본 이미지 모델
_IMAGE_MODEL_FALLBACKS = ("imagen-3.0", "imagen-3.0-light")  # SDK 가이드 기준 예비 후보
_STYLE_JSON_PATH = Path("illust_styles.json")

_ILLUST_STYLES_CACHE: list[dict] | None = None

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
def _build_title_prompt(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
) -> str:
    topic_clean = (topic or "").strip()
    return f"""당신은 어린이를 위한 동화 작가입니다.  
입력으로 나이대, 주제, 그리고 이야기 유형 설명이 주어집니다.  
이 정보를 활용하여 동화의 분위기와 핵심 갈등을 담은 **인상적인 한국어 제목**을 하나 만들어 주세요.  

- 나이대에 맞춘 어휘와 리듬을 고려하세요.  
- 이야기 유형 설명을 토대로 어떤 모험이나 정서를 담을지 상상하세요.  
- 주제 아이디어가 있다면 제목에 자연스럽게 녹여주세요.  
- 장면이나 감정을 직접 단정하지 말고, 이미지가 떠오르는 단어로 감각과 분위기를 암시하세요.  
- 한국 독자가 익숙한 자연스러운 표현을 사용하고, 문장은 간결하면서도 임팩트 있게 구성하세요.  
- 제목은 25자 이내로 작성하며 구두점을 사용하지 않습니다.  

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}

[출력 형식]
{{
  "title": "제목"
}}
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

    return f"""당신은 어린이를 위한 연속 동화 작가입니다.  
이 동화는 총 {total_count}단계 구조(발단-전개-위기-절정-결말)로 진행되며, 지금은 {stage_number}단계 "{stage_label}"을 작성합니다.  
앞선 단계들의 분위기와 인과를 이어가면서, 이번 단계만의 극적 역할을 분명히 하세요.  

[이전 단계 요약]
{previous_block}

[이번 단계 카드]
- 카드 이름: {story_card_name}
- 카드 설명: {card_prompt_clean}

[작성 지침]
- {stage_focus}
- 이전 단계와 자연스럽게 이어지도록 사건과 감정의 흐름을 조율하세요.
- 감정과 상황은 인물의 행동, 대사, 표정, 호흡, 몸짓, 주변 환경 묘사로 보여 주고, 단정적인 설명은 줄이세요. 필요하면 내적 독백과 미세한 감각 변화를 통해 심리를 드러내세요.
- 밝은 순간과 서늘한 긴장감이 공존하도록 하고, 모험 속 위기와 숨 돌릴 유머나 따뜻함을 함께 담으세요.
- 반전이나 정체성 전환은 한국어식 표현이나 대사로 드러내고, 영어식 구조를 사용하지 마세요.
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
) -> dict:
    """이야기와 스타일 정보를 바탕으로 이미지 생성 프롬프트를 구성."""
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

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

    directive = f"""당신은 어린이 그림책 삽화의 아트 디렉터이자 텍스트-투-이미지 프롬프트 엔지니어입니다.  주어진 동화 줄거리와 스타일 레퍼런스를 분석하여 **한 장의 삽화**를 묘사하는 영어 프롬프트를 작성하세요.  어린이 독자가 새로운 감정을 경험할 수 있도록, 스타일 고유의 분위기를 있는 그대로 살려 주세요.  
[Story]
- Title: {title or "(무제)"}
- Age Group: {age}
- Topic: {topic_text}
- Story Type: {story_type_name}
- Narrative Card: {story_card_name or "(선택 안 됨)"}
- Stage: {stage_name or "(단계 미지정)"}
- Summary: {summary}

[Style Reference]
- Illustrator: {style_name}
- Descriptor: {style_text}
- Style Traits:\n{traits_block}

[Requirements]
- 최종 문장은 순수 영어 프롬프트 한 단락으로 작성합니다 (불릿/설명 금지).
- "in the style of {style_name}" 구문을 반드시 포함합니다.
- 위 Style Traits에 나열된 표현들을 그대로 포함하고, 장면 묘사와 자연스럽게 연결하세요.
- 주요 등장인물과 핵심 사건, 배경, 감정, 조명, 색감을 구체적으로 묘사하세요.
- 스타일이 요구하는 분위기와 감정을 최우선으로 재현하고, 억지로 귀엽거나 안전하게 바꾸지 마세요.
- 생성 프롬프트에 "without text, typography, signature, or watermark"를 포함해 어떠한 글자/로고/싸인도 나오지 않도록 합니다.
"""

    last_error: dict | None = None
    for attempt in range(1, 4):
        try:
            model = genai.GenerativeModel(_MODEL)
            resp = model.generate_content(directive)
        except Exception as exc:
            last_error = {"error": f"{type(exc).__name__}: {exc}", "attempt": attempt}
            continue

        prompt_text = _extract_text_from_response(resp)
        final_prompt = (prompt_text or "").strip()
        if not final_prompt:
            last_error = {"error": "이미지 프롬프트 생성이 실패했습니다.", "attempt": attempt}
            continue

        if final_prompt.startswith("```"):
            cleaned = final_prompt.strip("`")
            cleaned_lines = [ln for ln in cleaned.splitlines() if not ln.strip().lower().startswith("prompt")]
            final_prompt = " ".join(line.strip() for line in cleaned_lines if line.strip()).strip()

        final_prompt = " ".join(final_prompt.split())

        return {
            "prompt": final_prompt,
            "style_name": style_name,
            "style_text": style_text,
        }

    if last_error is None:
        last_error = {"error": "이미지 프롬프트 생성이 실패했습니다."}
    last_error.setdefault("attempts", 3)
    return last_error

def generate_title_with_gemini(
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
) -> dict:
    """Gemini로 동화 제목을 생성."""
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    prompt = _build_title_prompt(age, topic, story_type_name, story_type_prompt)
    last_error: dict | None = None

    for attempt in range(1, 4):
        try:
            model = genai.GenerativeModel(_MODEL)
            resp = model.generate_content(prompt)
        except Exception as exc:
            last_error = {"error": f"{type(exc).__name__}: {exc}", "attempt": attempt}
            continue

        text = _extract_text_from_response(resp)
        if not text:
            last_error = {"error": "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)", "attempt": attempt}
            continue

        try:
            payload = json.loads(_strip_json_code_fence(text))
        except json.JSONDecodeError as exc:
            last_error = {"error": f"JSONDecodeError: {exc}", "attempt": attempt}
            continue

        title = (payload.get("title") or "").strip()
        if not title:
            last_error = {"error": "제목을 찾지 못했습니다.", "raw": payload, "attempt": attempt}
            continue

        return {"title": title}

    if last_error is None:
        last_error = {"error": "제목 생성에 실패했습니다."}
    last_error.setdefault("attempts", 3)
    return last_error

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
) -> dict:
    """
    Gemini로 단계별 동화를 생성해 {title, paragraphs[]} dict를 반환.
    실패 시 {"error": "..."} 반환.
    """
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

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
    )
    last_error: dict | None = None

    for attempt in range(1, 4):
        try:
            model = genai.GenerativeModel(_MODEL)
            resp = model.generate_content(prompt)
        except Exception as exc:
            last_error = {"error": f"{type(exc).__name__}: {exc}", "attempt": attempt}
            continue

        text = _extract_text_from_response(resp)
        if not text:
            last_error = {"error": "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)", "attempt": attempt}
            continue

        try:
            data = json.loads(_strip_json_code_fence(text))
        except json.JSONDecodeError as exc:
            fallback_payload = _extract_first_json_object(text)
            if fallback_payload is None:
                last_error = {"error": f"JSONDecodeError: {exc}", "attempt": attempt}
                continue
            try:
                data = json.loads(fallback_payload)
            except json.JSONDecodeError as exc_inner:
                last_error = {"error": f"JSONDecodeError: {exc_inner}", "attempt": attempt}
                continue

        paragraphs = data.get("paragraphs") or []
        if not isinstance(paragraphs, list) or not paragraphs:
            last_error = {"error": "반환 JSON 형식이 예상과 다릅니다.", "raw": data, "attempt": attempt}
            continue

        title_value = (data.get("title") or title or "").strip() or title
        cleaned_paragraphs = [str(p).strip() for p in paragraphs if str(p).strip()]
        if not cleaned_paragraphs:
            last_error = {"error": "본문 단락을 찾지 못했습니다.", "raw": data, "attempt": attempt}
            continue

        return {"title": title_value, "paragraphs": cleaned_paragraphs}

    if last_error is None:
        last_error = {"error": "동화 생성에 실패했습니다."}
    last_error.setdefault("attempts", 3)
    return last_error

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
    image_model_cls = getattr(genai, "ImageGenerationModel", None)
    if image_model_cls is not None:
        try:
            return image_model_cls(model_name=model_name)
        except TypeError:
            # 일부 버전은 positional-only 시그니처를 사용한다.
            return image_model_cls(model_name)
    return genai.GenerativeModel(model_name)


def _extract_image_from_response(resp):
    """Google Generative AI 응답 객체에서 이미지와 MIME 타입 추출."""
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            blob = getattr(part, "inline_data", None) or getattr(part, "data", None) or getattr(part, "blob", None)
            if blob is None:
                continue
            mime = getattr(blob, "mime_type", None)
            if isinstance(blob, dict):
                mime = blob.get("mime_type") or mime
                data = blob.get("data")
            else:
                data = getattr(blob, "data", None) or getattr(blob, "bytes", None)
            data_bytes = _coerce_bytes(data or blob)
            if data_bytes:
                return data_bytes, mime or "image/png"

    images = getattr(resp, "images", None) or getattr(resp, "generated_images", None) or []
    for img in images:
        mime = getattr(img, "mime_type", None) or getattr(img, "type", None) or "image/png"
        data_bytes = _coerce_bytes(
            getattr(img, "image_bytes", None)
            or getattr(img, "bytes", None)
            or getattr(img, "_image_bytes", None)
            or getattr(img, "data", None)
            or img
        )
        if data_bytes:
            return data_bytes, mime

    data_bytes = _coerce_bytes(getattr(resp, "data", None))
    if data_bytes:
        mime = getattr(resp, "mime_type", "image/png")
        return data_bytes, mime

    return None, None


def generate_image_with_gemini(prompt: str) -> dict:
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

        generate_images = getattr(model, "generate_images", None)
        if callable(generate_images):
            try:
                response = generate_images(prompt=prompt)
            except Exception as exc:
                last_exc = exc

        if response is None:
            generate_content = getattr(model, "generate_content", None)
            if callable(generate_content):
                try:
                    response = generate_content(prompt)
                    last_exc = None
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
            last_error = {"error": "모델이 이미지 데이터를 반환하지 않았습니다.", "attempt": attempt}
            continue

        return {"bytes": image_bytes, "mime_type": mime_type or "image/png"}

    if last_error is None:
        last_error = {"error": "이미지 생성에 실패했습니다."}
    last_error.setdefault("attempts", 3)
    return last_error
