# gemini_client.py
# ── 0) 로그 억제: gRPC/absl 메시지를 조용히 ──────────────────────────
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
