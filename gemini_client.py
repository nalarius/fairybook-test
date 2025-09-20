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
- 제목은 25자 이내로 간결하게 작성하고, 구두점은 사용하지 않습니다.  

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
    story_card_name: str,
    story_card_prompt: str,
) -> str:
    topic_clean = (topic or "").strip()
    safe_title = json.dumps(title.strip(), ensure_ascii=False) if title else '"동화"'
    return f"""당신은 어린이를 위한 동화 작가입니다.  
입력으로 나이대, 주제, 확정된 제목, 이야기 유형, 그리고 상세한 이야기 카드 설명이 주어집니다.  
이 정보를 모두 반영하여 **풍부하고 몰입감 있는 한국어 동화**를 완성하세요.  

- 제공된 제목을 그대로 사용하며, 제목에 어울리는 분위기와 상징을 전개하세요.  
- 이야기 카드 설명을 중심 갈등과 사건으로 적극 활용하세요.  
- 나이대에 맞는 문장 길이와 어휘를 선택하고, 주제를 이야기 전체의 정서와 갈등 전개에 자연스럽게 녹여 주세요.  
- 모험에는 위기나 갈등을 고려해 긴장감을 만들되, 안도와 기쁨이 숨 쉴 여백도 마련하세요. 착한 교훈으로만 마무리할 필요는 없습니다.  
- 장면 묘사, 인물 감정, 대화를 고르게 넣어 아이가 쉽게 상상할 수 있도록 하세요.  

동화는 최소 500자 이상이며, 다음 JSON 구조로만 출력합니다.  
{{
  "title": {safe_title},
  "paragraphs": ["첫 단락", "둘째 단락", "셋째 단락 이상"]
}}  
- 단락은 최소 3개 이상이며, 각 단락은 2~4문장으로 작성하세요.  
- 마지막 단락은 행복, 비극, 열린 결말 등 다양한 감정을 선택할 수 있으며, 교훈으로 정리할 필요는 없습니다.  

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 제목: {title.strip()}
- 이야기 유형: {story_type_name}
- 이야기 카드 이름: {story_card_name}
- 이야기 카드 설명: {story_card_prompt.strip()}
"""

def build_image_prompt(
    story: dict,
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    story_card_name: str | None = None,
) -> dict:
    """이야기와 스타일 정보를 바탕으로 이미지 생성 프롬프트를 구성."""
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    styles = _load_illust_styles()
    if not styles:
        return {"error": "illust_styles.json에서 사용할 수 있는 스타일을 찾지 못했습니다."}

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

    directive = f"""당신은 어린이 그림책 삽화의 아트 디렉터이자 텍스트-투-이미지 프롬프트 엔지니어입니다.  
주어진 동화 줄거리와 스타일 레퍼런스를 분석하여 **한 장의 삽화**를 묘사하는 영어 프롬프트를 작성하세요.  
어린이 독자가 새로운 감정을 경험할 수 있도록, 스타일 고유의 분위기를 있는 그대로 살려 주세요.  

[Story]
- Title: {title or "(무제)"}
- Age Group: {age}
- Topic: {topic_text}
- Story Type: {story_type_name}
- Narrative Card: {story_card_name or "(선택 안 됨)"}
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

    try:
        model = genai.GenerativeModel(_MODEL)
        resp = model.generate_content(directive)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    prompt_text = _extract_text_from_response(resp)
    final_prompt = (prompt_text or "").strip()
    if not final_prompt:
        return {"error": "이미지 프롬프트 생성이 실패했습니다."}

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
    try:
        model = genai.GenerativeModel(_MODEL)
        resp = model.generate_content(prompt)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    text = _extract_text_from_response(resp)
    if not text:
        return {"error": "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)"}

    try:
        payload = json.loads(_strip_json_code_fence(text))
    except json.JSONDecodeError as exc:
        return {"error": f"JSONDecodeError: {exc}"}

    title = (payload.get("title") or "").strip()
    if not title:
        return {"error": "제목을 찾지 못했습니다.", "raw": payload}

    return {"title": title}


def generate_story_with_gemini(
    age: str,
    topic: str | None,
    *,
    title: str,
    story_type_name: str,
    story_card_name: str,
    story_card_prompt: str,
) -> dict:
    """
    Gemini로 동화를 생성해 {title, paragraphs[]} dict를 반환.
    실패 시 {"error": "..."} 반환.
    """
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    prompt = _build_story_prompt(
        age=age,
        topic=topic,
        title=title,
        story_type_name=story_type_name,
        story_card_name=story_card_name,
        story_card_prompt=story_card_prompt,
    )
    try:
        model = genai.GenerativeModel(_MODEL)
        resp = model.generate_content(prompt)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    text = _extract_text_from_response(resp)
    if not text:
        return {"error": "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)"}

    try:
        data = json.loads(_strip_json_code_fence(text))
    except json.JSONDecodeError as exc:
        return {"error": f"JSONDecodeError: {exc}"}

    paragraphs = data.get("paragraphs") or []
    if not isinstance(paragraphs, list) or not paragraphs:
        return {"error": "반환 JSON 형식이 예상과 다릅니다.", "raw": data}

    title_value = (data.get("title") or title or "").strip() or title
    cleaned_paragraphs = [str(p).strip() for p in paragraphs if str(p).strip()]
    if not cleaned_paragraphs:
        return {"error": "본문 단락을 찾지 못했습니다.", "raw": data}

    return {"title": title_value, "paragraphs": cleaned_paragraphs}


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
        return {"error": f"이미지 모델 초기화 실패 — {detail}"}

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
            return {"error": "이미지 응답을 생성하지 못했습니다."}
        detail = f"{type(last_exc).__name__}: {last_exc}"
        if "NotFound" in detail or "404" in detail:
            detail += " — 사용 가능한 이미지 모델 이름을 ListModels로 확인하거나 GEMINI_IMAGE_MODEL 환경 변수를 설정해 주세요."
        if model_name:
            detail = f"[{model_name}] {detail}"
        return {"error": detail}

    image_bytes, mime_type = _extract_image_from_response(response)
    if not image_bytes:
        return {"error": "모델이 이미지 데이터를 반환하지 않았습니다."}

    return {"bytes": image_bytes, "mime_type": mime_type or "image/png"}
