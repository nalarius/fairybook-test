# gemini_client.py
# ── 0) 로그 억제: gRPC/absl 메시지를 조용히 ──────────────────────────
import base64
import os
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

def _build_prompt(age: str, topic: str | None, story_type_name: str) -> str:
    """입력(나이대/주제/유형)으로 짧은 동화 JSON을 요구하는 프롬프트 구성."""
    topic_clean = (topic or "").strip()
    return f"""당신은 어린이를 위한 동화 작가입니다.
입력으로 나이대, 주제, 이야기 유형이 주어집니다.
이에 맞춰 **짧은 동화**를 만들어 주세요.

[요구사항]
- 결과는 JSON 형식으로만 출력합니다. (설명/추가 텍스트 금지)
- JSON 구조:
{{
  "title": "동화 제목",
  "paragraphs": ["첫 단락", "둘째 단락"]
}}

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}

[출력 예시]
{{
  "title": "토끼와 모자의 모험",
  "paragraphs": [
    "햇살이 비치는 들판에서 작은 토끼가 모자를 발견했습니다.",
    "친구들과 함께 모자를 쓰고 신나는 놀이를 시작했습니다."
  ]
}}
"""

def generate_story_with_gemini(age: str, topic: str | None, story_type_name: str) -> dict:
    """
    Gemini로 동화를 생성해 {title, paragraphs[]} dict를 반환.
    실패 시 {"error": "..."} 반환.
    """
    if not API_KEY:
        return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}

    prompt = _build_prompt(age, topic, story_type_name)
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
