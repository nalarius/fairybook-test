"""Gemini SDK bootstrap and transport helpers."""
from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Tuple

from PIL import Image
from dotenv import load_dotenv

# Quiet gRPC/absl logs before importing the SDK.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_TRACE", "")
try:  # pragma: no cover - optional dependency
    from absl import logging as absl_logging

    absl_logging.set_verbosity(absl_logging.ERROR)
except Exception:  # pragma: no cover - absl not installed
    pass

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "")

_TEXT_MODEL_ENV = (os.getenv("GEMINI_TEXT_MODEL") or "").strip()
TEXT_MODEL = _TEXT_MODEL_ENV or "models/gemini-2.5-flash"

_IMAGE_MODEL_ENV = (os.getenv("GEMINI_IMAGE_MODEL") or "").strip()
IMAGE_MODEL = _IMAGE_MODEL_ENV or "gemini-1.5-flash"
IMAGE_MODEL_FALLBACKS: Tuple[str, ...] = tuple()

_GENAI_MODULE: Any | None = None
_GENAI_CONFIGURED = False
genai: Any = SimpleNamespace(GenerativeModel=None)


def missing_api_key_error() -> dict:
    return {"error": "GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인)."}


def require_api_key() -> dict | None:
    return None if API_KEY else missing_api_key_error()


def get_genai_module():
    """Lazily import and configure the ``google.generativeai`` SDK."""

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


@dataclass(frozen=True)
class TextGenerationResult:
    ok: bool
    payload: Any | None = None
    error: dict | None = None


def extract_text_from_response(resp) -> str:
    if hasattr(resp, "text") and resp.text:
        return str(resp.text)

    try:
        candidates = getattr(resp, "candidates", []) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) if content else None
            if parts:
                return " ".join(
                    getattr(part, "text", "") for part in parts if getattr(part, "text", "")
                )
    except Exception:
        return ""

    return ""


def generate_text_with_retry(
    prompt: str,
    *,
    attempts: int = 3,
    empty_error_message: str = "모델이 빈 응답을 반환했습니다. (세이프티 차단 가능)",
    parser: Callable[[str], Tuple[Any | None, dict | None]] | None = None,
    model_factory: Callable[[str], Any] | None = None,
    model_name: str | None = None,
) -> TextGenerationResult:
    if attempts < 1:
        attempts = 1

    genai_mod = None if model_factory else get_genai_module()
    factory = model_factory or genai_mod.GenerativeModel
    target_model = model_name or TEXT_MODEL
    last_error: dict | None = None

    for attempt in range(1, attempts + 1):
        try:
            model = factory(target_model)
            response = model.generate_content(prompt)
        except Exception as exc:
            last_error = {"error": f"{type(exc).__name__}: {exc}", "attempt": attempt}
            continue

        text = extract_text_from_response(response)
        text = (text or "").strip()
        if not text:
            last_error = {"error": empty_error_message, "attempt": attempt}
            continue

        if parser:
            parsed_payload, parse_error = parser(text)
            if parse_error is not None:
                last_error = {**parse_error, "attempt": attempt}
                continue
            return TextGenerationResult(ok=True, payload=parsed_payload)

        return TextGenerationResult(ok=True, payload=text)

    if last_error is None:
        last_error = {"error": "텍스트 생성에 실패했습니다.", "attempts": attempts}
    else:
        last_error.setdefault("attempts", attempts)
    return TextGenerationResult(ok=False, error=last_error)


def _coerce_bytes(value):
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


def _iter_image_models() -> Iterable[str]:
    seen = set()
    for name in (IMAGE_MODEL, *IMAGE_MODEL_FALLBACKS):
        if not name or name in seen:
            continue
        seen.add(name)
        yield name


def _instantiate_image_model(model_name: str):
    genai_mod = get_genai_module()
    return genai_mod.GenerativeModel(model_name)


def _extract_image_from_response(resp):
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


def generate_image(prompt: str, *, image_input: bytes | None = None) -> dict:
    if not API_KEY:
        return missing_api_key_error()

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


__all__ = [
    "API_KEY",
    "TEXT_MODEL",
    "IMAGE_MODEL",
    "IMAGE_MODEL_FALLBACKS",
    "genai",
    "get_genai_module",
    "generate_text_with_retry",
    "generate_image",
    "extract_text_from_response",
    "missing_api_key_error",
    "require_api_key",
    "TextGenerationResult",
]
