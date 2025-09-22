# app.py
import base64
import hashlib
import html
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from streamlit_image_select import image_select
from gemini_client import (
    generate_story_with_gemini,
    generate_image_with_gemini,
    build_image_prompt,
    build_character_image_prompt,
    generate_title_with_gemini,
    generate_synopsis_with_gemini,
    generate_protagonist_with_gemini,
)

st.set_page_config(page_title="동화책 생성기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
STYLE_JSON_PATH = "illust_styles.json"
STORY_JSON_PATH = "story.json"
ENDING_JSON_PATH = "ending.json"
ILLUST_DIR = "illust"
HTML_EXPORT_DIR = "html_exports"
HTML_EXPORT_PATH = Path(HTML_EXPORT_DIR)
HOME_BACKGROUND_IMAGE_PATH = Path("assets/illus-home-hero.png")

STORY_PHASES = ["발단", "전개", "위기", "절정", "결말"]
STAGE_GUIDANCE = {
    "발단": "주인공과 배경을 생생하게 소개하고 모험의 씨앗이 되는 사건을 담아주세요. 기대와 호기심, 포근함이 교차하도록 만듭니다.",
    "전개": "모험이 본격적으로 굴러가며 갈등이 커지도록 전개하세요. 긴장과 재미가 번갈아 오가고, 숨 돌릴 따뜻한 장면도 잊지 마세요.",
    "위기": "이야기의 가장 큰 위기가 찾아옵니다. 위험과 두려움이 느껴지되, 인물 간의 믿음과 재치도 함께 드러나야 합니다.",
    "절정": "결정적인 선택이나 행동으로 이야기가 뒤집히는 순간입니다. 장엄하거나 아슬아슬한 분위기와 함께 감정이 폭발하도록 그려주세요.",
    "결말": "사건의 여파를 정리하면서 여운을 남기세요. 밝은 마무리든 씁쓸한 끝맺음이든 자연스럽게 수용하고, 아이가 상상할 여백을 둡니다.",
}

HTML_EXPORT_PATH.mkdir(parents=True, exist_ok=True)

@st.cache_data
def load_story_types():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("story_types", [])

@st.cache_data
def load_illust_styles():
    try:
        with open(STYLE_JSON_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    return raw.get("illust_styles", [])


@st.cache_data
def load_story_cards():
    try:
        with open(STORY_JSON_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

    cards = raw.get("cards") or []
    return [card for card in cards if isinstance(card, dict)]


@st.cache_data
def load_ending_cards():
    try:
        with open(ENDING_JSON_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

    endings = raw.get("story_endings") or []
    return [ending for ending in endings if isinstance(ending, dict)]


@st.cache_data(show_spinner=False)
def load_image_as_base64(path: str) -> str | None:
    """지정된 경로의 이미지를 base64 문자열로 반환."""
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return None
    return base64.b64encode(data).decode("utf-8")


story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

illust_styles = load_illust_styles()
story_cards = load_story_cards()
ending_cards = load_ending_cards()

# ─────────────────────────────────────────────────────────────────────
# 세션 상태: '없을 때만' 기본값. 절대 무조건 대입하지 않음.
# ─────────────────────────────────────────────────────────────────────
def ensure_state():
    st.session_state.setdefault("step", 0)                 # 0: 선택, 1: 입력, 2: 유형/제목, 3: 표지 확인, 4: 카드 선택, 5: 단계 결과, 6: 전체 보기
    st.session_state.setdefault("mode", None)
    st.session_state.setdefault("age", None)               # 확정된 값(제출 후 저장)
    st.session_state.setdefault("topic", None)             # 확정된 값(제출 후 저장)
    st.session_state.setdefault("current_stage_idx", 0)
    if "stages_data" not in st.session_state or len(st.session_state["stages_data"]) != len(STORY_PHASES):
        st.session_state["stages_data"] = [None] * len(STORY_PHASES)
    # 입력폼 위젯 전용 임시 키(위젯 값 저장용). 최초 렌더에만 기본값 세팅
    st.session_state.setdefault("age_input", "6-8")
    st.session_state.setdefault("topic_input", "")
    # 유형 카드 8개
    if "rand8" not in st.session_state:
        st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types)))
    st.session_state.setdefault("selected_type_idx", 0)
    # 최신 생성 결과 유지 (스트림릿 리런 대응)
    st.session_state.setdefault("story_error", None)
    st.session_state.setdefault("story_result", None)
    st.session_state.setdefault("story_prompt", None)
    st.session_state.setdefault("story_image", None)
    st.session_state.setdefault("story_image_mime", "image/png")
    st.session_state.setdefault("story_image_style", None)
    st.session_state.setdefault("story_image_error", None)
    st.session_state.setdefault("synopsis_result", None)
    st.session_state.setdefault("synopsis_hooks", None)
    st.session_state.setdefault("synopsis_error", None)
    st.session_state.setdefault("is_generating_synopsis", False)
    st.session_state.setdefault("protagonist_result", None)
    st.session_state.setdefault("protagonist_error", None)
    st.session_state.setdefault("is_generating_protagonist", False)
    st.session_state.setdefault("character_prompt", None)
    st.session_state.setdefault("character_image", None)
    st.session_state.setdefault("character_image_mime", "image/png")
    st.session_state.setdefault("character_image_error", None)
    st.session_state.setdefault("is_generating_character_image", False)
    st.session_state.setdefault("selected_style_id", None)
    st.session_state.setdefault("story_title", None)
    st.session_state.setdefault("story_title_error", None)
    st.session_state.setdefault("story_cards_rand4", None)
    st.session_state.setdefault("selected_story_card_idx", 0)
    st.session_state.setdefault("story_card_choice", None)
    st.session_state.setdefault("story_export_path", None)
    st.session_state.setdefault("selected_export", None)
    st.session_state.setdefault("story_export_signature", None)
    st.session_state.setdefault("is_generating_title", False)
    st.session_state.setdefault("is_generating_story", False)
    st.session_state.setdefault("story_style_choice", None)
    st.session_state.setdefault("cover_image", None)
    st.session_state.setdefault("cover_image_mime", "image/png")
    st.session_state.setdefault("cover_image_style", None)
    st.session_state.setdefault("cover_image_error", None)
    st.session_state.setdefault("cover_prompt", None)
    st.session_state.setdefault("is_generating_all", False) # 통합 생성 플래그

ensure_state()

def go_step(n: int):
    st.session_state["step"] = n
    if n in (1, 2, 3, 4, 5, 6):
        st.session_state["mode"] = "create"


def reset_story_session(
    *,
    keep_title: bool = False,
    keep_cards: bool = False,
    keep_synopsis: bool = False,
    keep_protagonist: bool = False,
    keep_character: bool = False,
    keep_style: bool = False,
):
    defaults = {
        "story_error": None,
        "story_result": None,
        "story_prompt": None,
        "story_image": None,
        "story_image_mime": "image/png",
        "story_image_style": None,
        "story_image_error": None,
        "story_export_path": None,
        "story_export_signature": None,
        "story_title_error": None,
        "is_generating_story": False,
        "is_generating_title": False,
        "story_card_choice": None,
        "synopsis_result": None,
        "synopsis_hooks": None,
        "synopsis_error": None,
        "is_generating_synopsis": False,
        "protagonist_result": None,
        "protagonist_error": None,
        "is_generating_protagonist": False,
        "character_prompt": None,
        "character_image": None,
        "character_image_mime": "image/png",
        "character_image_error": None,
        "is_generating_character_image": False,
        "selected_style_id": None,
        "story_style_choice": None,
        "cover_image_style": None,
    }

    if keep_synopsis:
        for key in ("synopsis_result", "synopsis_hooks", "synopsis_error"):
            defaults.pop(key, None)
    if keep_protagonist:
        for key in ("protagonist_result", "protagonist_error"):
            defaults.pop(key, None)
    if keep_character:
        for key in ("character_prompt", "character_image", "character_image_mime", "character_image_error"):
            defaults.pop(key, None)
    if keep_style:
        for key in ("selected_style_id", "story_style_choice", "cover_image_style"):
            defaults.pop(key, None)

    for key, value in defaults.items():
        st.session_state[key] = value

    if not keep_title:
        st.session_state["story_title"] = None

    if not keep_cards:
        st.session_state["story_cards_rand4"] = None
        st.session_state["selected_story_card_idx"] = 0
def reset_all_state():
    keys = [
        "age",
        "topic",
        "age_input",
        "topic_input",
        "rand8",
        "selected_type_idx",
        "current_stage_idx",
        "story_error",
        "story_result",
        "story_prompt",
        "story_image",
        "story_image_mime",
        "story_image_style",
        "story_image_error",
        "story_title",
        "story_title_error",
        "story_cards_rand4",
        "selected_story_card_idx",
        "story_card_choice",
        "story_export_path",
        "story_export_signature",
        "selected_export",
        "is_generating_title",
        "is_generating_story",
        "is_generating_all",
        "stages_data",
        "story_style_choice",
        "cover_image",
        "cover_image_mime",
        "cover_image_style",
        "cover_image_error",
        "cover_prompt",
        "synopsis_result",
        "synopsis_hooks",
        "synopsis_error",
        "is_generating_synopsis",
        "protagonist_result",
        "protagonist_error",
        "is_generating_protagonist",
        "character_prompt",
        "character_image",
        "character_image_mime",
        "character_image_error",
        "is_generating_character_image",
        "selected_style_id",
    ]

    for key in keys:
        st.session_state.pop(key, None)

    st.session_state["mode"] = None
    st.session_state["step"] = 0


def clear_stages_from(index: int):
    stages = st.session_state.get("stages_data") or []
    if not stages:
        return
    clamped = max(0, min(index, len(stages)))
    for i in range(clamped, len(stages)):
        stages[i] = None
    st.session_state["stages_data"] = stages


def reset_character_art():
    st.session_state["character_prompt"] = None
    st.session_state["character_image"] = None
    st.session_state["character_image_mime"] = "image/png"
    st.session_state["character_image_error"] = None
    st.session_state["is_generating_character_image"] = False



def reset_title_and_cover(*, keep_style: bool = False, keep_title: bool = False):
    if not keep_title:
        st.session_state["story_title"] = None
        st.session_state["story_title_error"] = None
    st.session_state["is_generating_title"] = False
    st.session_state["cover_image"] = None
    st.session_state["cover_image_mime"] = "image/png"
    if not keep_style:
        st.session_state["cover_image_style"] = None
        st.session_state["story_style_choice"] = None
        st.session_state["selected_style_id"] = None
    st.session_state["cover_image_error"] = None
    st.session_state["cover_prompt"] = None



def reset_protagonist_state(*, keep_style: bool = True):
    st.session_state["protagonist_result"] = None
    st.session_state["protagonist_error"] = None
    st.session_state["is_generating_protagonist"] = False
    reset_character_art()
    reset_title_and_cover(keep_style=keep_style)



def reset_cover_art(*, keep_style: bool = False):
    reset_title_and_cover(keep_style=keep_style)


def format_item_list(values, limit: int | None = 3) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    elif isinstance(values, (tuple, set)):
        candidates = list(values)
    elif isinstance(values, list):
        candidates = values
    else:
        candidates = [values]
    cleaned: list[str] = []
    for item in candidates:
        text_item = str(item).strip()
        if text_item:
            cleaned.append(text_item)
    if limit is not None:
        return cleaned[:limit]
    return cleaned


def list_html_exports() -> list[Path]:
    """저장된 HTML 파일 목록(최신순)을 반환."""
    try:
        files = [p for p in HTML_EXPORT_PATH.glob("*.html") if p.is_file()]
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
    except Exception:
        return []


def _slugify_filename(value: str) -> str:
    """파일명에 안전하게 사용할 슬러그 생성."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    slug = value.strip("-")
    return slug or "story"


def _build_story_html_document(
    *,
    title: str,
    age: str,
    topic: str,
    story_type: str,
    stages: list[dict],
    cover: dict | None = None,
) -> str:
    escaped_title = html.escape(title)

    cover_section = ""
    if cover and cover.get("image_data_uri"):
        cover_section = (
            "    <section class=\"cover stage\">\n"
            "        <figure>\n"
            f"            <img src=\"{cover.get('image_data_uri')}\" alt=\"{escaped_title} 표지\" />\n"
            "        </figure>\n"
            "    </section>\n"
        )

    stage_sections: list[str] = []
    for idx, stage in enumerate(stages, start=1):
        image_data_uri = stage.get("image_data_uri") or ""
        paragraphs = stage.get("paragraphs") or []

        paragraphs_html = "\n".join(
            f"            <p>{html.escape(paragraph)}</p>" for paragraph in paragraphs
        ) or "            <p>(본문이 없습니다)</p>"

        image_section = (
            "        <figure>\n"
            f"            <img src=\"{image_data_uri}\" alt=\"{escaped_title} 삽화\" />\n"
            "        </figure>\n"
        ) if image_data_uri else ""

        section_html = (
            "    <section class=\"stage\">\n"
            f"{image_section}"
            f"{paragraphs_html}\n"
            "    </section>\n"
        )
        stage_sections.append(section_html)

    stages_html = "".join(stage_sections)

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "    <meta charset=\"utf-8\" />\n"
        f"    <title>{escaped_title}</title>\n"
        "    <style>\n"
        "        body { font-family: 'Noto Sans KR', sans-serif; margin: 2rem; background: #faf7f2; color: #2c2c2c; }\n"
        "        header { margin-bottom: 2.5rem; }\n"
        "        h1 { font-size: 2rem; margin-bottom: 0.5rem; }\n"
        "        .cover { margin-bottom: 3rem; }\n"
        "        .stage { margin-bottom: 3rem; padding-bottom: 2rem; border-bottom: 1px solid rgba(0,0,0,0.08); }\n"
        "        .stage:last-of-type { border-bottom: none; }\n"
        "        figure { text-align: center; margin: 1.5rem auto; }\n"
        "        figure img { max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 12px 36px rgba(0,0,0,0.12); }\n"
        "        figcaption { font-size: 0.9rem; color: #666; margin-top: 0.5rem; }\n"
        "        p { line-height: 1.65; font-size: 1.05rem; margin-bottom: 1rem; }\n"
        "    </style>\n"
        "</head>\n"
        "<body>\n"
        "    <header>\n"
        f"        <h1>{escaped_title}</h1>\n"
        "    </header>\n"
        f"{cover_section}{stages_html}"
        "</body>\n"
        "</html>\n"
    )


def export_story_to_html(
    *,
    title: str,
    age: str,
    topic: str | None,
    story_type: str,
    stages: list[dict],
    cover: dict | None = None,
) -> str:
    """다단계 이야기와 삽화를 하나의 HTML 파일로 저장하고 경로를 반환."""
    HTML_EXPORT_PATH.mkdir(parents=True, exist_ok=True)

    normalized_stages: list[dict] = []
    for stage in stages:
        paragraphs_raw = stage.get("paragraphs") or []
        paragraphs = [str(p).strip() for p in paragraphs_raw if str(p).strip()]
        image_bytes = stage.get("image_bytes")
        image_mime = stage.get("image_mime") or "image/png"
        image_data_uri = None
        if image_bytes:
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            image_data_uri = f"data:{image_mime};base64,{encoded}"

        normalized_stages.append(
            {
                "stage_name": stage.get("stage_name", "단계"),
                "card_name": stage.get("card_name"),
                "card_prompt": stage.get("card_prompt"),
                "paragraphs": paragraphs,
                "image_data_uri": image_data_uri,
                "image_style_name": stage.get("image_style_name"),
            }
        )

    cover_section = None
    if cover and cover.get("image_bytes"):
        image_bytes = cover.get("image_bytes")
        image_mime = cover.get("image_mime") or "image/png"
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        cover_section = {
            "image_data_uri": f"data:{image_mime};base64,{encoded}",
            "style_name": cover.get("style_name"),
        }

    safe_title = title.strip() or "동화"
    html_doc = _build_story_html_document(
        title=safe_title,
        age=age,
        topic=topic or "",
        story_type=story_type,
        stages=normalized_stages,
        cover=cover_section,
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_filename(safe_title)
    filename = f"{timestamp}_{slug}.html"
    export_path = HTML_EXPORT_PATH / filename

    with export_path.open("w", encoding="utf-8") as f:
        f.write(html_doc)

    return str(export_path)

# ─────────────────────────────────────────────────────────────────────
# 헤더/진행
# ─────────────────────────────────────────────────────────────────────
st.title("📖 동화책 생성기")
progress_placeholder = st.empty()
mode = st.session_state.get("mode")
current_step = st.session_state["step"]

if mode == "create" and current_step > 0:
    total_phases = len(STORY_PHASES)
    completed_stages = sum(1 for stage in st.session_state.get("stages_data", []) if stage)
    progress_value = 0.0
    if current_step == 1:
        progress_value = 0.15
    elif current_step == 2:
        progress_value = 0.25
    elif current_step == 3:
        progress_value = 0.35
    elif current_step in (4, 5):
        stage_share = completed_stages / total_phases if total_phases else 0.0
        progress_value = 0.35 + stage_share * 0.6
    elif current_step == 6:
        if completed_stages >= total_phases:
            progress_value = 1.0
        else:
            stage_share = completed_stages / total_phases if total_phases else 0.0
            progress_value = 0.35 + stage_share * 0.6
    progress_placeholder.progress(min(progress_value, 1.0))
else:
    progress_placeholder.empty()

if current_step == 0:
    st.caption("원하는 작업을 선택해주세요.")
elif mode == "create":
    st.caption("차근차근 동화를 완성해보세요.")
else:
    st.caption("저장된 동화를 살펴볼 수 있어요.")

# ─────────────────────────────────────────────────────────────────────
# STEP 1 — 나이대/주제 입력 (form으로 커밋 시점 고정, 확정 키와 분리)
# ─────────────────────────────────────────────────────────────────────
if current_step == 0:
    home_bg = load_image_as_base64(str(HOME_BACKGROUND_IMAGE_PATH))
    if home_bg:
        st.markdown(
            f"""
            <style>
            .stApp {{
                background: linear-gradient(180deg, #f6f2ff 0%, #fff8f2 68%, #ffffff 100%);
            }}
            [data-testid="stHeader"] {{
                background: rgba(0, 0, 0, 0);
            }}
            [data-testid="stAppViewContainer"] > .main > div:first-child {{
                background-color: rgba(255, 255, 255, 0.9);
                border-radius: 20px;
                padding: 1.75rem 2rem;
                box-shadow: 0 18px 44px rgba(0, 0, 0, 0.12);
                backdrop-filter: blur(1.5px);
                max-width: 780px;
            }}
            [data-testid="stAppViewContainer"] > .main > div:first-child h1 {{
                margin-bottom: 0.2rem;
            }}
            .home-hero {{
                width: 100%;
                height: 570px;
                margin: 0.18rem 0 0.5rem;
                background-position: center;
                background-repeat: no-repeat;
                background-size: contain;
            }}
            @media (max-width: 640px) {{
                .home-hero {{
                    height: 360px;
                    margin: 0.15rem 0 0.45rem;
                }}
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class=\"home-hero\" style=\"background-image: url('data:image/png;base64,{home_bg}');\"></div>",
            unsafe_allow_html=True,
        )
    st.subheader("어떤 작업을 하시겠어요?")
    exports_available = bool(list_html_exports())

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ 동화 만들기", use_container_width=True):
            reset_all_state()
            ensure_state()
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.rerun()
    with c2:
        view_clicked = st.button(
            "📂 저장본 보기",
            use_container_width=True,
            disabled=not exports_available,
        )
        if view_clicked:
            st.session_state["mode"] = "view"
            st.session_state["step"] = 5

    if not exports_available:
        st.caption("저장된 동화가 아직 없습니다. 먼저 동화를 만들어 저장해 주세요.")

elif current_step == 1:
    st.subheader("1단계. 나이대와 이야기 아이디어를 입력하세요")

    # 폼 제출 전까지는 age/topic을 건드리지 않음
    with st.form("step1_form", clear_on_submit=False):
        st.selectbox(
            "나이대",
            ["6-8", "9-12"],
            index=0 if st.session_state["age_input"] == "6-8" else 1,
            key="age_input",  # 위젯은 age_input에만 바인딩
        )
        st.caption("이야기의 주제, 진행 방향, 주요 인물 등을 자유롭게 입력해주세요.")
        st.text_area(
            "이야기 아이디어",
            placeholder="예) 꼬마 제이가 동물 친구들과 함께 잃어버린 모자를 찾는 모험 이야기",
            height=96,
            key="topic_input",  # 위젯은 topic_input에만 바인딩
        )
        c1, c2 = st.columns(2)
        go_next = c1.form_submit_button("다음 단계로 →", use_container_width=True)
        do_reset = c2.form_submit_button("입력 초기화", use_container_width=True)

    if do_reset:
        # 임시 위젯 값만 초기화. 확정값(age/topic)은 건드리지 않음.
        st.session_state["age_input"] = "6-8"
        st.session_state["topic_input"] = ""

    if go_next:
        # 이 시점에만 확정 키로 복사
        reset_story_session(keep_title=False, keep_cards=False)
        clear_stages_from(0)
        reset_cover_art()
        st.session_state["current_stage_idx"] = 0
        st.session_state["age"] = st.session_state["age_input"]
        st.session_state["topic"] = (st.session_state["topic_input"] or "").strip()
        st.session_state["step"] = 2

elif current_step == 2:
    st.subheader("2단계. 제목을 만들어보세요.")

    rand8 = st.session_state["rand8"]
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    selected_idx = st.session_state.get("selected_type_idx", 0)
    if selected_idx >= len(rand8):
        selected_idx = max(0, len(rand8) - 1)
    st.session_state["selected_type_idx"] = selected_idx
    selected_type = rand8[selected_idx]

    age_val = st.session_state["age"] if st.session_state["age"] else "6-8"
    topic_val = st.session_state["topic"] if (st.session_state["topic"] is not None) else ""
    topic_display = topic_val if topic_val else "(빈칸)"
    type_prompt = (selected_type.get("prompt") or "").strip()
    story_type_name = selected_type.get("name", "이야기 유형")

    if st.session_state.get("is_generating_all"):
        st.header("동화의 씨앗을 심고 있어요 🌱")
        st.caption("이야기의 첫 단추를 꿰는 중입니다. 잠시만 기다려주세요.")
        progress_bar = st.progress(0.0, "시작하는 중...")

        def show_error_and_stop(message: str):
            st.error(message)
            st.session_state["is_generating_all"] = False
            if st.button("다시 시도하기", use_container_width=True):
                reset_story_session()
                st.rerun()
            st.stop()

        # 1. 시놉시스 생성
        progress_bar.progress(0.1, "시놉시스를 만들고 있어요...")
        synopsis_result = generate_synopsis_with_gemini(
            age=age_val,
            topic=topic_val or None,
            story_type_name=story_type_name,
            story_type_prompt=type_prompt,
        )
        if "error" in synopsis_result:
            show_error_and_stop(f"시놉시스 생성 실패: {synopsis_result['error']}")
        synopsis_text = (synopsis_result.get("synopsis") or "").strip()
        st.session_state["synopsis_result"] = synopsis_text

        # 2. 주인공 설정 생성
        progress_bar.progress(0.25, "주인공을 상상하고 있어요...")
        protagonist_result = generate_protagonist_with_gemini(
            age=age_val,
            topic=topic_val or None,
            story_type_name=story_type_name,
            story_type_prompt=type_prompt,
            synopsis_text=synopsis_text,
        )
        if "error" in protagonist_result:
            show_error_and_stop(f"주인공 설정 생성 실패: {protagonist_result['error']}")
        protagonist_text = (protagonist_result.get("description") or "").strip()
        st.session_state["protagonist_result"] = protagonist_text

        # 3. 삽화 스타일 랜덤 결정
        progress_bar.progress(0.4, "삽화 스타일을 고르고 있어요...")
        if not illust_styles:
            show_error_and_stop("삽화 스타일을 찾을 수 없습니다. illust_styles.json을 확인해주세요.")
        style_choice = random.choice(illust_styles)
        st.session_state["story_style_choice"] = style_choice
        st.session_state["cover_image_style"] = style_choice
        st.session_state["selected_style_id"] = illust_styles.index(style_choice)

        # 4. 주인공 설정화 생성
        progress_bar.progress(0.55, "주인공의 모습을 그리고 있어요...")
        char_prompt_data = build_character_image_prompt(
            age=age_val,
            topic=topic_val,
            story_type_name=story_type_name,
            synopsis_text=synopsis_text,
            protagonist_text=protagonist_text,
            style_override=style_choice,
        )
        if "error" in char_prompt_data:
            st.warning(f"주인공 설정화 프롬프트 생성 실패: {char_prompt_data['error']}")
        else:
            st.session_state["character_prompt"] = char_prompt_data.get("prompt")
            char_image_resp = generate_image_with_gemini(char_prompt_data["prompt"])
            if "error" in char_image_resp:
                st.warning(f"주인공 설정화 생성 실패: {char_image_resp['error']}")
                st.session_state["character_image_error"] = char_image_resp["error"]
            else:
                st.session_state["character_image"] = char_image_resp.get("bytes")
                st.session_state["character_image_mime"] = char_image_resp.get("mime_type", "image/png")

        # 5. 제목 생성
        progress_bar.progress(0.7, "멋진 제목을 짓고 있어요...")
        title_result = generate_title_with_gemini(
            age=age_val,
            topic=topic_val or None,
            story_type_name=story_type_name,
            story_type_prompt=type_prompt,
            synopsis=synopsis_text,
            protagonist=protagonist_text,
        )
        if "error" in title_result:
            show_error_and_stop(f"제목 생성 실패: {title_result['error']}")
        title_text = title_result.get("title", "").strip()
        if not title_text:
            show_error_and_stop("생성된 제목이 비어 있습니다.")
        st.session_state["story_title"] = title_text

        # 6. 표지 이미지 생성
        progress_bar.progress(0.85, "표지를 디자인하고 있어요...")
        cover_story = {"title": title_text, "paragraphs": [synopsis_text, protagonist_text]}
        cover_prompt_data = build_image_prompt(
            story=cover_story,
            age=age_val,
            topic=topic_val,
            story_type_name=story_type_name,
            story_card_name="표지 컨셉",
            stage_name="표지",
            style_override=style_choice,
            use_reference_image=st.session_state.get("character_image") is not None,
        )
        if "error" in cover_prompt_data:
            st.warning(f"표지 프롬프트 생성 실패: {cover_prompt_data['error']}")
        else:
            st.session_state["cover_prompt"] = cover_prompt_data.get("prompt")
            cover_image_resp = generate_image_with_gemini(
                cover_prompt_data["prompt"],
                image_input=st.session_state.get("character_image"),
            )
            if "error" in cover_image_resp:
                st.warning(f"표지 이미지 생성 실패: {cover_image_resp['error']}")
                st.session_state["cover_image_error"] = cover_image_resp["error"]
            else:
                st.session_state["cover_image"] = cover_image_resp.get("bytes")
                st.session_state["cover_image_mime"] = cover_image_resp.get("mime_type", "image/png")

        progress_bar.progress(1.0, "완성! 다음 화면으로 이동합니다.")
        st.session_state["is_generating_all"] = False
        go_step(3)
        st.rerun()
        st.stop()

    st.caption("마음에 드는 이야기 유형 카드를 클릭한 뒤, '제목 만들기' 버튼을 눌러주세요.")
    type_images = [os.path.join(ILLUST_DIR, t.get("illust", "")) for t in rand8]
    type_captions = [t.get("name", "이야기 유형") for t in rand8]

    sel_idx = image_select(
        label="",
        images=type_images,
        captions=type_captions,
        use_container_width=True,
        return_value="index",
        key="rand8_picker",
    )
    if sel_idx is not None and sel_idx != selected_idx:
        st.session_state["selected_type_idx"] = sel_idx
        reset_story_session()
        st.rerun()
        st.stop()

    st.success(f"선택된 이야기 유형: **{story_type_name}**")
    st.write(f"나이대: **{age_val}**, 주제: **{topic_display}**")
    if type_prompt:
        st.caption(f"유형 설명: {type_prompt}")

    st.markdown("---")

    if st.button("✨ 제목 만들기", type="primary", use_container_width=True):
        reset_story_session()
        st.session_state["is_generating_all"] = True
        st.rerun()
        st.stop()

    st.markdown("---")
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 이야기 아이디어 다시 입력", use_container_width=True):
            reset_story_session()
            go_step(1)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 유형 뽑기", use_container_width=True):
            st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types))) if story_types else []
            st.session_state["selected_type_idx"] = 0
            reset_story_session()
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()


# STEP 3 — 표지 확인
# ─────────────────────────────────────────────────────────────────────
elif current_step == 3:
    st.subheader("3단계. 완성된 제목과 표지를 확인해보세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", use_container_width=True):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    cover_image = st.session_state.get("cover_image")
    cover_error = st.session_state.get("cover_image_error")
    cover_style = st.session_state.get("cover_image_style") or st.session_state.get("story_style_choice")
    synopsis_text = st.session_state.get("synopsis_result")
    protagonist_text = st.session_state.get("protagonist_result")
    character_image = st.session_state.get("character_image")
    character_error = st.session_state.get("character_image_error")
    style_choice = st.session_state.get("story_style_choice")

    st.markdown(f"### {title_val}")
    if cover_image:
        caption = "표지 일러스트"
        if cover_style and cover_style.get("name"):
            caption += f" · {cover_style.get('name')} 스타일"
        st.image(cover_image, caption=caption, use_container_width=True)
    elif cover_error:
        st.warning(f"표지 일러스트 생성 실패: {cover_error}")
    else:
        st.info("표지 일러스트가 아직 준비되지 않았어요. 제목을 다시 생성해 보세요.")

    st.markdown("---")
    st.markdown("#### 간단한 시놉시스")
    if synopsis_text:
        st.write(synopsis_text)
    else:
        st.info("시놉시스가 비어 있습니다. 2단계에서 다시 생성해 주세요.")

    st.markdown("---")
    st.markdown("#### 주인공 상세 설정")
    if protagonist_text:
        st.write(protagonist_text)
    else:
        st.info("주인공 설정이 없습니다. 2단계에서 다시 생성해 주세요.")

    st.markdown("---")
    st.markdown("#### 주인공 설정화")
    if character_image:
        caption = "주인공 설정화"
        active_style = style_choice or cover_style
        if active_style and active_style.get("name"):
            caption += f" · {active_style.get('name')} 스타일"
        st.image(character_image, caption=caption, use_container_width=True)
    elif character_error:
        st.warning(f"설정화 생성 실패: {character_error}")
    else:
        st.info("설정화가 아직 없습니다. 2단계에서 스타일을 선택하고 생성해 주세요.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 제목 다시 만들기", use_container_width=True):
            reset_story_session()
            go_step(2)
            st.rerun()
            st.stop()

    with c2:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

    with c3:
        continue_disabled = not title_val
        if st.button("계속해서 이야기 만들기 →", type="primary", use_container_width=True, disabled=continue_disabled):
            clear_stages_from(0)
            st.session_state["current_stage_idx"] = 0
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            st.session_state["step"] = 4
            st.rerun()
            st.stop()

elif current_step == 4 and mode == "create":
    stage_idx = st.session_state.get("current_stage_idx", 0)
    if stage_idx >= len(STORY_PHASES):
        st.session_state["step"] = 6
        st.rerun()
        st.stop()

    stage_name = STORY_PHASES[stage_idx]
    card_instruction = "엔딩" if stage_name == STORY_PHASES[-1] else "이야기"
    st.subheader(f"4단계. {stage_idx + 1} {stage_name}에 어울리는 {card_instruction} 카드를 골라보세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", use_container_width=True):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    is_final_stage = stage_name == STORY_PHASES[-1]
    available_cards = ending_cards if is_final_stage else story_cards

    if not available_cards:
        missing_msg = "ending.json" if is_final_stage else "story.json"
        st.error(f"{missing_msg}에서 사용할 수 있는 이야기 카드를 찾지 못했습니다.")
        if st.button("처음으로 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    rand8 = st.session_state.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    selected_type_idx = st.session_state.get("selected_type_idx", 0)
    if selected_type_idx >= len(rand8):
        selected_type_idx = max(0, len(rand8) - 1)
        st.session_state["selected_type_idx"] = selected_type_idx
    selected_type = rand8[selected_type_idx]

    age_val = st.session_state["age"] if st.session_state["age"] else "6-8"
    topic_val = st.session_state["topic"] if (st.session_state["topic"] is not None) else ""
    topic_display = topic_val if topic_val else "(빈칸)"

    guidance = STAGE_GUIDANCE.get(stage_name)
    if guidance:
        st.caption(guidance)
    if is_final_stage:
        st.caption("이 단계에서는 `ending.json`에 정의된 엔딩 카드를 사용해 결말의 분위기를 골라보세요.")

    style_choice = st.session_state.get("story_style_choice")
    if style_choice and style_choice.get("name"):
        st.caption(f"삽화 스타일은 **{style_choice.get('name')}**로 유지됩니다.")

    previous_sections = [entry for entry in (st.session_state.get("stages_data") or [])[:stage_idx] if entry]
    if previous_sections:
        with st.expander("이전 단계 줄거리 다시 보기", expanded=False):
            for idx, entry in enumerate(previous_sections, start=1):
                stage_label = entry.get("stage") or f"단계 {idx}"
                st.markdown(f"**{stage_label}** — {entry.get('card', {}).get('name', '카드 미지정')}")
                for paragraph in entry.get("story", {}).get("paragraphs", []):
                    st.write(paragraph)

    cards = st.session_state.get("story_cards_rand4")
    if not cards:
        sample_size = min(4, len(available_cards))
        if sample_size <= 0:
            source_label = "ending.json" if is_final_stage else "story.json"
            st.error(f"카드가 부족합니다. {source_label}을 확인해주세요.")
            if st.button("처음으로 돌아가기", use_container_width=True):
                reset_all_state()
                st.rerun()
                st.stop()
            st.stop()
        st.session_state["story_cards_rand4"] = random.sample(available_cards, k=sample_size)
        st.session_state["selected_story_card_idx"] = 0
        cards = st.session_state["story_cards_rand4"]

    selected_card_idx = st.session_state.get("selected_story_card_idx", 0)
    if selected_card_idx >= len(cards):
        selected_card_idx = max(0, len(cards) - 1)
        st.session_state["selected_story_card_idx"] = selected_card_idx
    selected_card = cards[selected_card_idx]

    st.markdown(f"**제목:** {title_val}")
    st.caption(
        f"나이대: **{age_val}** · 주제: **{topic_display}** · 이야기 유형: **{selected_type.get('name', '이야기 유형')}**"
    )
    st.caption("카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요. 단계별로 생성된 내용은 자동으로 이어집니다.")

    card_images = [os.path.join(ILLUST_DIR, card.get("illust", "")) for card in cards]
    card_captions = [card.get("name", "이야기 카드") for card in cards]

    selected_idx = image_select(
        label="",
        images=card_images,
        captions=card_captions,
        use_container_width=True,
        return_value="index",
        key="story_card_picker",
    )
    if selected_idx is not None:
        st.session_state["selected_story_card_idx"] = selected_idx
        selected_card = cards[selected_idx]

    card_prompt = (selected_card.get("prompt") or "").strip()
    card_label = "엔딩 카드" if is_final_stage else "이야기 카드"
    st.success(f"선택된 {card_label}: **{selected_card.get('name', card_label)}**")
    if card_prompt:
        st.caption(card_prompt)

    stages_data = st.session_state.get("stages_data") or []
    existing_stage = stages_data[stage_idx] if stage_idx < len(stages_data) else None
    if existing_stage:
        st.warning("이미 완성된 단계가 있어 새로 만들면 덮어씁니다.")

    if st.button("이 단계 이야기 만들기", type="primary", use_container_width=True):
        reset_story_session(keep_title=True, keep_cards=True, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
        st.session_state["story_prompt"] = None
        st.session_state["is_generating_story"] = True
        st.session_state["step"] = 5
        st.rerun()
        st.stop()

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 제목 다시 만들기", use_container_width=True):
            clear_stages_from(0)
            st.session_state["current_stage_idx"] = 0
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            go_step(2)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 카드 뽑기", use_container_width=True):
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

# ─────────────────────────────────────────────────────────────────────
# STEP 5 — 생성 중 상태 & 결과 보기
# ─────────────────────────────────────────────────────────────────────
elif current_step == 5 and mode == "create":
    stage_idx = st.session_state.get("current_stage_idx", 0)
    if stage_idx >= len(STORY_PHASES):
        st.session_state["step"] = 6
        st.rerun()
        st.stop()

    stage_name = STORY_PHASES[stage_idx]
    st.subheader(f"4단계. {stage_idx + 1} {stage_name} 이야기를 확인하세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", use_container_width=True):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    cards = st.session_state.get("story_cards_rand4")
    if not cards:
        st.warning("이야기 카드를 다시 선택해주세요.")
        if st.button("이야기 카드 화면으로", use_container_width=True):
            go_step(4)
            st.rerun()
            st.stop()
        st.stop()

    rand8 = st.session_state.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    age_val = st.session_state["age"] if st.session_state["age"] else "6-8"
    topic_val = st.session_state["topic"] if (st.session_state["topic"] is not None) else ""
    topic_display = topic_val if topic_val else "(빈칸)"
    selected_type = rand8[st.session_state.get("selected_type_idx", 0)]

    selected_card_idx = st.session_state.get("selected_story_card_idx", 0)
    if selected_card_idx >= len(cards):
        selected_card_idx = max(0, len(cards) - 1)
        st.session_state["selected_story_card_idx"] = selected_card_idx
    selected_card = cards[selected_card_idx]
    card_name = selected_card.get("name", "이야기 카드")
    card_prompt = (selected_card.get("prompt") or "").strip()

    previous_sections = []
    for entry in (st.session_state.get("stages_data") or [])[:stage_idx]:
        if not entry:
            continue
        previous_sections.append(
            {
                "stage": entry.get("stage"),
                "card_name": entry.get("card", {}).get("name"),
                "paragraphs": entry.get("story", {}).get("paragraphs", []),
            }
        )

    if st.session_state.get("is_generating_story"):
        st.header("동화를 준비하고 있어요 ✨")
        st.caption(f"{stage_name} 단계에 맞춰 이야기를 확장하고 있습니다.")

        with st.spinner("이야기와 삽화를 준비 중..."):
            clear_stages_from(stage_idx)
            story_result = generate_story_with_gemini(
                age=age_val,
                topic=topic_val or None,
                title=title_val,
                story_type_name=selected_type.get("name", "이야기 유형"),
                stage_name=stage_name,
                stage_index=stage_idx,
                total_stages=len(STORY_PHASES),
                story_card_name=card_name,
                story_card_prompt=card_prompt,
                previous_sections=previous_sections,
                synopsis_text=st.session_state.get("synopsis_result"),
                protagonist_text=st.session_state.get("protagonist_result"),
            )

            if "error" in story_result:
                st.session_state["story_error"] = story_result["error"]
                st.session_state["story_result"] = None
                st.session_state["story_prompt"] = None
                st.session_state["story_image"] = None
                st.session_state["story_image_error"] = None
                st.session_state["story_image_style"] = None
                st.session_state["story_image_mime"] = "image/png"
                st.session_state["story_card_choice"] = None
            else:
                story_payload = dict(story_result)
                story_payload["title"] = title_val.strip() if title_val else story_payload.get("title", "")
                st.session_state["story_error"] = None
                st.session_state["story_result"] = story_payload
                st.session_state["story_card_choice"] = {
                    "name": card_name,
                    "prompt": card_prompt,
                    "stage": stage_name,
                }

                style_choice = st.session_state.get("story_style_choice")
                if not style_choice and illust_styles:
                    fallback_style = random.choice(illust_styles)
                    style_choice = {
                        "name": fallback_style.get("name"),
                        "style": fallback_style.get("style"),
                    }
                    st.session_state["story_style_choice"] = style_choice
                elif not style_choice:
                    st.session_state["story_error"] = "삽화 스타일을 불러오지 못했습니다. illust_styles.json을 확인해주세요."
                    st.session_state["story_result"] = story_payload
                    st.session_state["story_prompt"] = None
                    st.session_state["story_image"] = None
                    st.session_state["story_image_error"] = "삽화 스타일이 없어 생성을 중단했습니다."
                    st.session_state["story_image_style"] = None
                    st.session_state["story_image_mime"] = "image/png"
                    st.session_state["is_generating_story"] = False
                    st.rerun()
                    st.stop()

                prompt_data = build_image_prompt(
                    story=story_payload,
                    age=age_val,
                    topic=topic_val,
                    story_type_name=selected_type.get("name", "이야기 유형"),
                    story_card_name=card_name,
                    stage_name=stage_name,
                    style_override=style_choice,
                    use_reference_image=st.session_state.get("character_image") is not None,
                    protagonist_text=st.session_state.get("protagonist_result"),
                )

                if "error" in prompt_data:
                    st.session_state["story_prompt"] = None
                    st.session_state["story_image_error"] = prompt_data["error"]
                    st.session_state["story_image_style"] = None
                    st.session_state["story_image"] = None
                    st.session_state["story_image_mime"] = "image/png"
                else:
                    st.session_state["story_prompt"] = prompt_data["prompt"]
                    style_info = {
                        "name": prompt_data.get("style_name") or (style_choice or {}).get("name"),
                        "style": prompt_data.get("style_text") or (style_choice or {}).get("style"),
                    }
                    st.session_state["story_image_style"] = style_info
                    st.session_state["story_style_choice"] = style_info

                    image_response = generate_image_with_gemini(
                        prompt_data["prompt"],
                        image_input=st.session_state.get("character_image"),
                    )
                    if "error" in image_response:
                        st.session_state["story_image_error"] = image_response["error"]
                        st.session_state["story_image"] = None
                        st.session_state["story_image_mime"] = "image/png"
                    else:
                        st.session_state["story_image_error"] = None
                        st.session_state["story_image"] = image_response.get("bytes")
                        st.session_state["story_image_mime"] = image_response.get("mime_type", "image/png")

                stages_copy = list(st.session_state.get("stages_data") or [None] * len(STORY_PHASES))
                while len(stages_copy) < len(STORY_PHASES):
                    stages_copy.append(None)
                stages_copy[stage_idx] = {
                    "stage": stage_name,
                    "card": {
                        "name": card_name,
                        "prompt": card_prompt,
                    },
                    "story": story_payload,
                    "image_bytes": st.session_state.get("story_image"),
                    "image_mime": st.session_state.get("story_image_mime"),
                    "image_style": st.session_state.get("story_image_style"),
                    "image_prompt": st.session_state.get("story_prompt"),
                    "image_error": st.session_state.get("story_image_error"),
                }
                st.session_state["stages_data"] = stages_copy

        st.session_state["is_generating_story"] = False
        st.rerun()
        st.stop()

    story_error = st.session_state.get("story_error")
    stages_data = st.session_state.get("stages_data") or []
    stage_entry = stages_data[stage_idx] if stage_idx < len(stages_data) else None
    story_data = stage_entry.get("story") if stage_entry else st.session_state.get("story_result")

    if not story_data and not story_error:
        st.info("이야기 카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요.")
        if st.button("이야기 카드 화면으로", use_container_width=True):
            go_step(4)
            st.rerun()
            st.stop()
        st.stop()

    if story_error:
        st.error(f"이야기 생성 실패: {story_error}")
        retry_col, card_col, reset_col = st.columns(3)
        with retry_col:
            if st.button("다시 시도", use_container_width=True):
                st.session_state["story_error"] = None
                st.session_state["is_generating_story"] = True
                st.rerun()
                st.stop()
        with card_col:
            if st.button("카드 다시 고르기", use_container_width=True):
                clear_stages_from(stage_idx)
                reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
                go_step(4)
                st.rerun()
                st.stop()
        with reset_col:
            if st.button("모두 초기화", use_container_width=True):
                reset_all_state()
                st.rerun()
                st.stop()
        st.stop()

    if not story_data:
        st.stop()

    for paragraph in story_data.get("paragraphs", []):
        st.write(paragraph)

    image_bytes = stage_entry.get("image_bytes") if stage_entry else st.session_state.get("story_image")
    image_error = stage_entry.get("image_error") if stage_entry else st.session_state.get("story_image_error")

    if image_bytes:
        st.image(image_bytes, caption="AI 생성 삽화", use_container_width=True)
    elif image_error:
        st.warning(f"삽화 생성 실패: {image_error}")

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 카드 다시 고르기", use_container_width=True):
            clear_stages_from(stage_idx)
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            go_step(4)
            st.rerun()
            st.stop()
    with nav_col2:
        stage_completed = stage_entry is not None
        if stage_idx < len(STORY_PHASES) - 1:
            if st.button(
                "다음 단계로 →",
                use_container_width=True,
                disabled=not stage_completed,
            ):
                st.session_state["current_stage_idx"] = stage_idx + 1
                reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
                go_step(4)
                st.rerun()
                st.stop()
        else:
            if st.button(
                "이야기 모아보기 →",
                use_container_width=True,
                disabled=not stage_completed,
            ):
                st.session_state["step"] = 6
                reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
                st.rerun()
                st.stop()
    with nav_col3:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

    if stage_entry and stage_idx < len(STORY_PHASES) - 1:
        if st.button("이야기 모아보기", use_container_width=True):
            st.session_state["step"] = 6
            st.rerun()
            st.stop()

elif current_step == 6 and mode == "create":
    st.subheader("6단계. 이야기를 모아봤어요")

    title_val = (st.session_state.get("story_title") or "동화").strip()
    age_val = st.session_state.get("age") or "6-8"
    topic_val = st.session_state.get("topic") or ""
    topic_display = topic_val if topic_val else "(빈칸)"
    rand8 = st.session_state.get("rand8") or []
    selected_type_idx = st.session_state.get("selected_type_idx", 0)
    story_type_name = (
        rand8[selected_type_idx].get("name", "이야기 유형")
        if 0 <= selected_type_idx < len(rand8)
        else "이야기 유형"
    )

    stages_data = st.session_state.get("stages_data") or []
    completed_stages = [entry for entry in stages_data if entry]

    if len(completed_stages) < len(STORY_PHASES):
        st.info("아직 모든 단계가 완성되지 않았어요. 남은 단계를 이어가면 이야기가 더 풍성해집니다.")
        try:
            next_stage_idx = next(idx for idx, entry in enumerate(stages_data) if not entry)
        except StopIteration:
            next_stage_idx = len(STORY_PHASES) - 1

        if st.button("남은 단계 이어가기 →", use_container_width=True):
            st.session_state["current_stage_idx"] = next_stage_idx
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            st.session_state["step"] = 4
            st.rerun()
        st.stop()

    cover_image = st.session_state.get("cover_image")
    cover_error = st.session_state.get("cover_image_error")
    cover_style = st.session_state.get("story_style_choice") or st.session_state.get("cover_image_style")

    export_ready_stages: list[dict] = []
    display_sections: list[dict] = []
    text_lines: list[str] = [title_val, ""]
    signature_payload = {
        "title": title_val,
        "age": age_val,
        "topic": topic_val or "",
        "story_type": story_type_name,
        "stages": [],
        "cover_hash": None,
    }

    for idx, stage_name in enumerate(STORY_PHASES):
        entry = stages_data[idx] if idx < len(stages_data) else None
        if not entry:
            display_sections.append({"missing": stage_name})
            continue
        card_info = entry.get("card", {})
        story_info = entry.get("story", {})
        paragraphs = story_info.get("paragraphs", [])
        text_lines.extend(paragraphs)
        text_lines.append("")

        image_bytes = entry.get("image_bytes")
        image_hash = hashlib.sha256(image_bytes).hexdigest() if image_bytes else None

        export_ready_stages.append(
            {
                "stage_name": stage_name,
                "card_name": card_info.get("name"),
                "card_prompt": card_info.get("prompt"),
                "paragraphs": paragraphs,
                "image_bytes": image_bytes,
                "image_mime": entry.get("image_mime"),
                "image_style_name": (entry.get("image_style") or {}).get("name"),
            }
        )
        signature_payload["stages"].append(
            {
                "stage_name": stage_name,
                "card_name": card_info.get("name"),
                "paragraphs": paragraphs,
                "image_hash": image_hash,
            }
        )
        display_sections.append(
            {
                "image_bytes": image_bytes,
                "image_error": entry.get("image_error"),
                "paragraphs": paragraphs,
            }
        )

    full_text = "\n".join(line for line in text_lines if line is not None)

    cover_payload = None
    cover_hash = None
    if cover_image:
        cover_mime = st.session_state.get("cover_image_mime", "image/png")
        cover_payload = {
            "image_bytes": cover_image,
            "image_mime": cover_mime,
            "style_name": (cover_style or {}).get("name"),
        }
        cover_hash = hashlib.sha256(cover_image).hexdigest()

    signature_payload["cover_hash"] = cover_hash
    signature_raw = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
    signature = hashlib.sha256(signature_raw.encode("utf-8")).hexdigest()

    auto_saved = False
    if st.session_state.get("story_export_signature") != signature:
        try:
            export_path = export_story_to_html(
                title=title_val,
                age=age_val,
                topic=topic_val,
                story_type=story_type_name,
                stages=export_ready_stages,
                cover=cover_payload,
            )
            st.session_state["story_export_path"] = export_path
            st.session_state["selected_export"] = export_path
            st.session_state["story_export_signature"] = signature
            auto_saved = True
        except Exception as exc:
            st.error(f"HTML 자동 저장 실패: {exc}")

    export_path_current = st.session_state.get("story_export_path")
    if auto_saved and export_path_current:
        st.success(f"HTML 자동 저장 완료: {export_path_current}")

    st.markdown(f"### {title_val}")
    if cover_image:
        st.image(cover_image, use_container_width=True)
    elif cover_error:
        st.caption("표지 일러스트를 준비하지 못했어요.")

    last_export = st.session_state.get("story_export_path")
    if last_export:
        st.caption(f"최근 저장 파일: {last_export}")
    else:
        st.caption("전체 이야기가 준비되면 자동으로 HTML로 저장돼요.")

    for idx, section in enumerate(display_sections):
        if section.get("missing"):
            st.warning("이야기 단계가 비어 있습니다. 다시 생성해 주세요.")
            continue

        image_bytes = section.get("image_bytes")
        image_error = section.get("image_error")
        paragraphs = section.get("paragraphs") or []

        if image_bytes:
            st.image(image_bytes, use_container_width=True)
        elif image_error:
            st.caption("삽화를 준비하지 못했어요.")

        for paragraph in paragraphs:
            st.write(paragraph)

        if idx < len(display_sections) - 1:
            st.markdown("---")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 첫 화면으로", use_container_width=True):
            reset_all_state()
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", use_container_width=True):
            reset_all_state()
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.rerun()
    with c3:
        if st.button("📂 저장한 동화 보기", use_container_width=True):
            st.session_state["mode"] = "view"
            st.session_state["step"] = 5
            st.rerun()

elif current_step == 5 and mode == "view":
    st.subheader("저장한 동화 보기")
    exports = list_html_exports()

    if not exports:
        st.info("저장된 동화가 없습니다. 먼저 동화를 생성해주세요.")
    else:
        options = []
        for path in exports:
            modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            options.append(f"{path.name} · {modified}")

        selected_path_str = st.session_state.get("selected_export")
        default_index = 0
        if selected_path_str:
            try:
                default_index = next(
                    idx for idx, path in enumerate(exports) if str(path) == selected_path_str
                )
            except StopIteration:
                default_index = 0

        selection = st.selectbox(
            "읽고 싶은 동화를 선택하세요",
            options,
            index=default_index,
        )

        selected_path = exports[options.index(selection)]
        st.session_state["selected_export"] = str(selected_path)

        try:
            html_content = selected_path.read_text("utf-8")
        except Exception as exc:
            st.error(f"동화를 여는 데 실패했습니다: {exc}")
        else:
            st.download_button(
                "동화 다운로드",
                data=html_content,
                file_name=selected_path.name,
                mime="text/html",
                use_container_width=True,
            )
            st.caption(f"파일 경로: {selected_path}")
            components.html(html_content, height=700, scrolling=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("← 선택 화면으로", use_container_width=True):
            st.session_state["mode"] = None
            st.session_state["step"] = 0
            st.session_state["selected_export"] = None
            st.session_state["story_export_path"] = None
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", use_container_width=True):
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.rerun()
