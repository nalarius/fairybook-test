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

def _build_story_prompt(age: str, topic: str | None, story_type_name: str) -> str:
    """입력(나이대/주제/유형)으로 짧은 동화 JSON을 요구하는 프롬프트 구성."""
    topic_clean = (topic or "").strip()
    return f"""당신은 어린이를 위한 동화 작가입니다.  
입력으로 나이대, 주제, 이야기 유형이 주어집니다.  
이에 맞춰 **풍부하고 재미있는 동화**를 만들어 주세요.  

- 반드시 '나이대'에 적합한 어휘와 문장 길이를 사용하고, 이해하기 쉽게 설명해주세요.  
- '주제'는 단순히 언급만 하지 말고, 이야기 전체의 중심 갈등이나 사건으로 녹여내어야 합니다.  
- '유형'에 맞게 이야기 구조를 정하고, 모험, 환상, 교훈, 유머 등 해당 유형의 매력을 충분히 살려주세요.  

동화는 다음 요소를 반드시 포함해야 합니다:  
1. **매력적인 주인공**: 개성과 감정을 가진 주인공을 소개하세요.  
2. **갈등과 사건 전개**: 주제와 관련된 문제나 모험이 일어나도록 하고, 점차 긴장감을 쌓아 올리세요.  
3. **다양한 장면 묘사**: 배경(계절, 장소, 분위기)을 구체적으로 묘사하여 독자가 그림을 떠올릴 수 있게 하세요.  
4. **대화**: 인물들이 감정을 드러낼 수 있도록 대화를 적극적으로 넣으세요.  
5. **해결과 교훈**: 마지막에는 주제와 연결된 따뜻한 깨달음, 교훈, 혹은 유쾌한 반전을 담아 마무리하세요.  

동화는 최소 500자 이상, 풍부한 묘사와 사건 전개로 아이가 몰입할 수 있게 작성하세요.  

[요구사항]  
- 결과는 JSON 형식으로만 출력합니다. (설명/추가 텍스트 금지)  
- JSON 구조:  
{{
  "title": "동화 제목",
  "paragraphs": ["첫 단락", "둘째 단락", "셋째 단락 이상"]
}}  
- 단락은 최소 3개 이상 작성하세요.  
- 각 단락은 2~4문장 정도로 구성하며, 생생한 묘사와 간단한 대화를 포함하세요.  
- '나이대'에 맞는 어휘를 사용하고, '주제'가 사건 전개의 중심이 되도록 하세요.  
- '이야기 유형'에 맞게 모험, 환상, 유머, 교훈 등의 색깔을 살리세요.  
- 마지막 단락은 따뜻한 결말이나 작은 교훈으로 마무리하세요.  

[입력]  
- 나이대: {age}  
- 주제: {topic_clean if topic_clean else "(빈칸)"}  
- 이야기 유형: {story_type_name}  

[출력 예시]  
{{
  "title": "토끼와 모자의 모험",
  "paragraphs": [
    "햇살이 가득한 들판에서 작은 토끼가 커다란 모자를 발견했습니다.",
    "\"이 모자를 쓰면 하늘을 날 수 있을까?\" 토끼는 설레는 마음으로 속삭였습니다.",
    "친구들이 몰려와 함께 모자를 쓰고 달리기 시작했지요. 모두 웃음소리를 터뜨렸습니다.",
    "마지막에 토끼는 깨달았어요. '모자가 아니라 우리 우정이 가장 큰 마법이구나!'"
  ]
}}
"""

def build_image_prompt(
    story: dict,
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
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

[Story]
- Title: {title or "(무제)"}
- Age Group: {age}
- Topic: {topic_text}
- Story Type: {story_type_name}
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
- 생성될 image 에 글자가 등장하지 않도록 합니다.
"""

    try:
        model = genai.GenerativeModel(_MODEL)
        resp = model.generate_content(directive)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    prompt_text = ""
    if hasattr(resp, "text") and resp.text:
        prompt_text = resp.text
    else:
        try:
            cands = getattr(resp, "candidates", []) or []
            if cands and hasattr(cands[0], "content") and getattr(cands[0].content, "parts", None):
                parts = cands[0].content.parts
                prompt_text = " ".join([getattr(p, "text", "") for p in parts if getattr(p, "text", "")])
        except Exception:
            pass

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


def generate_story_with_gemini(age: str, topic: str | None, story_type_name: str) -> dict:
    """
    Gemini로 동화를 생성해 {title, paragraphs[]} dict를 반환.
    실패 시 {"error": "..."} 반환.
    """
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    prompt = _build_story_prompt(age, topic, story_type_name)
    try:
        model = genai.GenerativeModel(_MODEL)
        resp = model.generate_content(prompt)

        # 텍스트 확보 (text 또는 candidates.parts)
        text = ""
        if hasattr(resp, "text") and resp.text:
            text = resp.text
        else:
            try:
                cands = getattr(resp, "candidates", []) or []
                if cands and hasattr(cands[0], "content") and getattr(cands[0].content, "parts", None):
                    parts = cands[0].content.parts
                    text = " ".join([getattr(p, "text", "") for p in parts if getattr(p, "text", "")])
            except Exception:
                pass

        if not text:
            return {"error": "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)"}

        # 코드블록(```json ... ```) 제거
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            t = "\n".join([ln for ln in t.splitlines() if not ln.strip().lower().startswith("json")])

        data = json.loads(t)
        title = (data.get("title") or "").strip()
        paragraphs = data.get("paragraphs") or []
        if not title or not isinstance(paragraphs, list) or not paragraphs:
            return {"error": "반환 JSON 형식이 예상과 다릅니다.", "raw": data}

        return {"title": title, "paragraphs": [str(p).strip() for p in paragraphs if str(p).strip()]}

    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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
