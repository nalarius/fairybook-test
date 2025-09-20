# app.py
import base64
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
    generate_title_with_gemini,
)

st.set_page_config(page_title="한 줄 동화 만들기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
STYLE_JSON_PATH = "illust_styles.json"
STORY_JSON_PATH = "story.json"
ILLUST_DIR = "illust"
HTML_EXPORT_DIR = "html_exports"
HTML_EXPORT_PATH = Path(HTML_EXPORT_DIR)

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


story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

illust_styles = load_illust_styles()
story_cards = load_story_cards()

# ─────────────────────────────────────────────────────────────────────
# 세션 상태: '없을 때만' 기본값. 절대 무조건 대입하지 않음.
# ─────────────────────────────────────────────────────────────────────
def ensure_state():
    st.session_state.setdefault("step", 0)                 # 0: 선택, 1: 입력, 2: 유형/제목, 3: 카드 선택, 4: 결과, 5: 보기
    st.session_state.setdefault("mode", None)
    st.session_state.setdefault("age", None)               # 확정된 값(제출 후 저장)
    st.session_state.setdefault("topic", None)             # 확정된 값(제출 후 저장)
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
    st.session_state.setdefault("story_title", None)
    st.session_state.setdefault("story_title_error", None)
    st.session_state.setdefault("story_cards_rand4", None)
    st.session_state.setdefault("selected_story_card_idx", 0)
    st.session_state.setdefault("story_card_choice", None)
    st.session_state.setdefault("story_export_path", None)
    st.session_state.setdefault("selected_export", None)
    st.session_state.setdefault("is_generating_title", False)
    st.session_state.setdefault("is_generating_story", False)

ensure_state()

def go_step(n: int):
    st.session_state["step"] = n
    if n in (1, 2, 3, 4):
        st.session_state["mode"] = "create"


def reset_story_session(*, keep_title: bool = False, keep_cards: bool = False):
    defaults = {
        "story_error": None,
        "story_result": None,
        "story_prompt": None,
        "story_image": None,
        "story_image_mime": "image/png",
        "story_image_style": None,
        "story_image_error": None,
        "story_export_path": None,
        "story_title_error": None,
        "is_generating_story": False,
        "is_generating_title": False,
        "story_card_choice": None,
    }

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
        "selected_export",
        "is_generating_title",
        "is_generating_story",
    ]

    for key in keys:
        st.session_state.pop(key, None)

    st.session_state["mode"] = None
    st.session_state["step"] = 0


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
    paragraphs: list[str],
    age: str,
    topic: str,
    story_type: str,
    style_name: str | None,
    image_data_uri: str | None,
) -> str:
    escaped_title = html.escape(title)
    topic_text = topic if topic else "(빈칸)"
    meta_parts = [
        f"<strong>나이대:</strong> {html.escape(age)}",
        f"<strong>주제:</strong> {html.escape(topic_text)}",
        f"<strong>이야기 유형:</strong> {html.escape(story_type)}",
    ]
    if style_name:
        meta_parts.append(f"<strong>삽화 스타일:</strong> {html.escape(style_name)}")
    meta_html = " · ".join(meta_parts)

    paragraphs_html = "\n".join(
        f"        <p>{html.escape(paragraph)}</p>" for paragraph in paragraphs
    ) or "        <p>(본문이 없습니다)</p>"

    image_section = ""
    if image_data_uri:
        image_section = (
            "        <figure>\n"
            f"            <img src=\"{image_data_uri}\" alt=\"{escaped_title} 삽화\" />\n"
            "        </figure>\n"
        )

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "    <meta charset=\"utf-8\" />\n"
        f"    <title>{escaped_title}</title>\n"
        "    <style>\n"
        "        body { font-family: 'Noto Sans KR', sans-serif; margin: 2rem; background: #faf7f2; color: #2c2c2c; }\n"
        "        header { margin-bottom: 2rem; }\n"
        "        h1 { font-size: 2rem; margin-bottom: 0.5rem; }\n"
        "        .meta { color: #555; margin-bottom: 1.5rem; }\n"
        "        figure { text-align: center; margin: 2rem auto; }\n"
        "        figure img { max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }\n"
        "        p { line-height: 1.6; font-size: 1.05rem; margin-bottom: 1rem; }\n"
        "    </style>\n"
        "</head>\n"
        "<body>\n"
        "    <header>\n"
        f"        <h1>{escaped_title}</h1>\n"
        f"        <p class=\"meta\">{meta_html}</p>\n"
        "    </header>\n"
        "    <section>\n"
        f"{image_section}{paragraphs_html}\n"
        "    </section>\n"
        "</body>\n"
        "</html>\n"
    )


def export_story_to_html(
    story: dict,
    image_bytes: bytes | None,
    image_mime: str | None,
    *,
    age: str,
    topic: str | None,
    story_type: str,
    style_name: str | None,
) -> str:
    """이야기와 삽화를 하나의 HTML 파일로 저장하고 경로를 반환."""
    HTML_EXPORT_PATH.mkdir(parents=True, exist_ok=True)

    title = (story.get("title") or "동화").strip()
    paragraphs = story.get("paragraphs") or []

    image_data_uri = None
    if image_bytes:
        mime = image_mime or "image/png"
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        image_data_uri = f"data:{mime};base64,{encoded}"

    html_doc = _build_story_html_document(
        title=title or "동화",
        paragraphs=[str(p) for p in paragraphs],
        age=age,
        topic=topic or "",
        story_type=story_type,
        style_name=style_name,
        image_data_uri=image_data_uri,
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_filename(title)
    filename = f"{timestamp}_{slug}.html"
    export_path = HTML_EXPORT_PATH / filename

    with export_path.open("w", encoding="utf-8") as f:
        f.write(html_doc)

    return str(export_path)

# ─────────────────────────────────────────────────────────────────────
# 헤더/진행
# ─────────────────────────────────────────────────────────────────────
st.title("📖 한 줄 주제로 동화 만들기")
progress_placeholder = st.empty()
mode = st.session_state.get("mode")
current_step = st.session_state["step"]

if mode == "create" and current_step in (1, 2, 3, 4):
    progress_map = {1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0}
    progress_placeholder.progress(progress_map.get(current_step, 0.0))
else:
    progress_placeholder.empty()

if current_step == 0:
    st.caption("원하는 작업을 선택해주세요.")
elif mode == "create":
    st.caption("제목을 정하고 이야기 카드를 골라 차근차근 동화를 완성해보세요.")
else:
    st.caption("저장된 동화를 살펴볼 수 있어요.")

# ─────────────────────────────────────────────────────────────────────
# STEP 1 — 나이대/주제 입력 (form으로 커밋 시점 고정, 확정 키와 분리)
# ─────────────────────────────────────────────────────────────────────
if current_step == 0:
    st.subheader("어떤 작업을 하시겠어요?")
    exports_available = bool(list_html_exports())

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ 동화 만들기", use_container_width=True):
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
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
        st.caption("저장된 HTML 파일이 아직 없습니다. 먼저 동화를 만들어 저장해 주세요.")

elif current_step == 1:
    st.subheader("1단계. 나이대와 주제를 고르세요")

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
            placeholder="예) 잃어버린 모자를 찾는 모험에서 동물 친구들이 함께 돕는 이야기",
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
        st.session_state["age"] = st.session_state["age_input"]
        st.session_state["topic"] = (st.session_state["topic_input"] or "").strip()
        st.session_state["step"] = 2

# ─────────────────────────────────────────────────────────────────────
# STEP 2 — 이야기 유형 선택 & 제목 생성
# ─────────────────────────────────────────────────────────────────────
elif current_step == 2:
    st.subheader("2단계. 이야기 유형을 고르고 제목을 만들어보세요")

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
    type_prompt = (selected_type.get("prompt") or "").strip()

    if st.session_state.get("is_generating_title"):
        st.header("제목을 준비하고 있어요 ✨")
        st.caption("조금만 기다려 주세요. Gemini로 제목을 만들고 있습니다.")

        with st.spinner("Gemini로 제목을 만드는 중..."):
            result = generate_title_with_gemini(
                age=age_val,
                topic=topic_val or None,
                story_type_name=selected_type.get("name", "이야기 유형"),
                story_type_prompt=type_prompt,
            )

            if "error" in result:
                st.session_state["story_title_error"] = result["error"]
            else:
                title_text = result.get("title", "").strip()
                reset_story_session(keep_title=False, keep_cards=False)
                st.session_state["story_title"] = title_text
                st.session_state["story_title_error"] = None
                st.session_state["step"] = 3

        st.session_state["is_generating_title"] = False
        st.rerun()
        st.stop()

    st.caption("마음에 드는 이야기 유형 카드를 클릭하세요. 선택 후 '제목 만들기' 버튼을 누르면 추천 제목이 생성됩니다.")
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
    if sel_idx is not None:
        st.session_state["selected_type_idx"] = sel_idx
        selected_type = rand8[sel_idx]
        type_prompt = (selected_type.get("prompt") or "").strip()

    topic_display = topic_val if topic_val else "(빈칸)"
    st.success(f"선택된 이야기 유형: **{selected_type.get('name', '이야기 유형')}**")
    st.write(f"나이대: **{age_val}**, 주제: **{topic_display}**")
    if type_prompt:
        st.caption(f"유형 설명: {type_prompt}")

    title_existing = st.session_state.get("story_title")
    if st.session_state.get("story_title_error"):
        st.error(st.session_state["story_title_error"])
    elif title_existing:
        st.info(f"생성된 제목: **{title_existing}**")

    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        if st.button("제목 만들기", type="primary", use_container_width=True):
            st.session_state["story_title_error"] = None
            st.session_state["is_generating_title"] = True
            st.rerun()
            st.stop()
    with btn_col2:
        if st.button(
            "이야기 카드 고르러 가기 →",
            use_container_width=True,
            disabled=not st.session_state.get("story_title"),
        ):
            st.session_state["step"] = 3
            st.rerun()
            st.stop()
    with btn_col3:
        if st.button("새로운 8개 뽑기", use_container_width=True):
            st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types))) if story_types else []
            st.session_state["selected_type_idx"] = 0
            reset_story_session()
            st.rerun()
            st.stop()

    back_col, reset_col = st.columns(2)
    with back_col:
        if st.button("← 나이/주제 다시 선택", use_container_width=True):
            reset_story_session()
            go_step(1)
            st.rerun()
            st.stop()
    with reset_col:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

# ─────────────────────────────────────────────────────────────────────
# STEP 3 — 이야기 카드 선택
# ─────────────────────────────────────────────────────────────────────
elif current_step == 3:
    st.subheader("3단계. 이야기 카드를 골라보세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", use_container_width=True):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    if not story_cards:
        st.error("story.json에서 사용할 수 있는 이야기 카드를 찾지 못했습니다.")
        if st.button("처음으로 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    age_val = st.session_state["age"] if st.session_state["age"] else "6-8"
    topic_val = st.session_state["topic"] if (st.session_state["topic"] is not None) else ""
    topic_display = topic_val if topic_val else "(빈칸)"

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

    cards = st.session_state.get("story_cards_rand4")
    if not cards:
        sample_size = min(4, len(story_cards))
        if sample_size <= 0:
            st.error("이야기 카드가 부족합니다. story.json을 확인해주세요.")
            if st.button("처음으로 돌아가기", use_container_width=True):
                reset_all_state()
                st.rerun()
                st.stop()
            st.stop()
        st.session_state["story_cards_rand4"] = random.sample(story_cards, k=sample_size)
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
    st.caption("카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요.")

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
    st.success(f"선택된 이야기 카드: **{selected_card.get('name', '이야기 카드')}**")
    if card_prompt:
        st.caption(card_prompt)

    if st.button("이야기 만들기", type="primary", use_container_width=True):
        reset_story_session(keep_title=True, keep_cards=True)
        st.session_state["is_generating_story"] = True
        st.session_state["step"] = 4
        st.rerun()
        st.stop()

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 제목 다시 만들기", use_container_width=True):
            reset_story_session(keep_title=True, keep_cards=False)
            go_step(2)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 4개 뽑기", use_container_width=True):
            reset_story_session(keep_title=True, keep_cards=False)
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

# ─────────────────────────────────────────────────────────────────────
# STEP 4 — 생성 중 상태 & 결과 보기
# ─────────────────────────────────────────────────────────────────────
elif current_step == 4:
    st.subheader("4단계. 완성된 동화를 만나보세요")

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
            go_step(3)
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

    if st.session_state.get("is_generating_story"):
        st.header("동화를 준비하고 있어요 ✨")
        st.caption("조금만 기다려 주세요. 선택한 카드에 맞춰 이야기를 생성하는 중입니다.")

        with st.spinner("Gemini로 동화와 삽화를 준비 중..."):
            story_result = generate_story_with_gemini(
                age=age_val,
                topic=topic_val or None,
                title=title_val,
                story_type_name=selected_type.get("name", "이야기 유형"),
                story_card_name=card_name,
                story_card_prompt=card_prompt,
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
                }

                prompt_data = build_image_prompt(
                    story=story_payload,
                    age=age_val,
                    topic=topic_val,
                    story_type_name=selected_type.get("name", "이야기 유형"),
                    story_card_name=card_name,
                )

                if "error" in prompt_data:
                    st.session_state["story_prompt"] = None
                    st.session_state["story_image_error"] = prompt_data["error"]
                    st.session_state["story_image_style"] = None
                    st.session_state["story_image"] = None
                    st.session_state["story_image_mime"] = "image/png"
                else:
                    st.session_state["story_prompt"] = prompt_data["prompt"]
                    st.session_state["story_image_style"] = {
                        "name": prompt_data.get("style_name"),
                        "style": prompt_data.get("style_text"),
                    }

                    image_response = generate_image_with_gemini(prompt_data["prompt"])
                    if "error" in image_response:
                        st.session_state["story_image_error"] = image_response["error"]
                        st.session_state["story_image"] = None
                        st.session_state["story_image_mime"] = "image/png"
                    else:
                        st.session_state["story_image_error"] = None
                        st.session_state["story_image"] = image_response.get("bytes")
                        st.session_state["story_image_mime"] = image_response.get("mime_type", "image/png")

        st.session_state["is_generating_story"] = False
        st.rerun()
        st.stop()

    story_data = st.session_state.get("story_result")
    story_error = st.session_state.get("story_error")

    if not story_data and not story_error:
        st.info("이야기 카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요.")
        if st.button("이야기 카드 화면으로", use_container_width=True):
            go_step(3)
            st.rerun()
            st.stop()
        st.stop()

    meta_caption = (
        f"나이대: **{age_val}** · 주제: **{topic_display}** · 이야기 유형: **{selected_type.get('name', '이야기 유형')}**"
    )

    display_title = story_data.get("title", title_val) if story_data else title_val
    st.subheader(display_title)
    st.caption(meta_caption)
    st.caption(f"선택한 이야기 카드: **{card_name}**")
    if card_prompt:
        st.caption(card_prompt)

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
                reset_story_session(keep_title=True, keep_cards=True)
                go_step(3)
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

    st.download_button(
        "텍스트 다운로드",
        data=(
            story_data.get("title", title_val)
            + "\n\n"
            + "\n".join(story_data.get("paragraphs", []))
        ),
        file_name="fairytale.txt",
        mime="text/plain",
        use_container_width=True,
    )

    style_info = st.session_state.get("story_image_style")
    image_bytes = st.session_state.get("story_image")
    image_error = st.session_state.get("story_image_error")
    image_mime = st.session_state.get("story_image_mime")

    if style_info:
        st.caption(f"삽화 스타일: {style_info.get('name', '알 수 없음')}")

    if image_bytes:
        st.image(image_bytes, caption="AI 생성 삽화", use_container_width=True)
    elif image_error:
        st.warning(f"삽화 생성 실패: {image_error}")

    if st.button("HTML로 저장", use_container_width=True):
        try:
            export_path = export_story_to_html(
                story=story_data,
                image_bytes=image_bytes,
                image_mime=image_mime,
                age=age_val,
                topic=topic_val,
                story_type=selected_type.get("name", "이야기 유형"),
                style_name=style_info.get("name") if style_info else None,
            )
            st.session_state["story_export_path"] = export_path
            st.session_state["selected_export"] = export_path
            st.success(f"HTML 저장 완료: {export_path}")
        except Exception as exc:
            st.error(f"HTML 저장 실패: {exc}")

    last_export = st.session_state.get("story_export_path")
    if last_export:
        st.caption(f"최근 저장 파일: {last_export}")

    prompt_text = st.session_state.get("story_prompt")
    if prompt_text:
        with st.expander("이미지 프롬프트 보기", expanded=False):
            st.code(prompt_text)

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 이야기 카드 다시 고르기", use_container_width=True):
            reset_story_session(keep_title=True, keep_cards=True)
            go_step(3)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 4개 뽑기", use_container_width=True):
            reset_story_session(keep_title=True, keep_cards=False)
            go_step(3)
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", use_container_width=True):
            reset_all_state()
            st.rerun()
            st.stop()

elif current_step == 5:
    st.subheader("저장된 동화 보기")
    exports = list_html_exports()

    if not exports:
        st.info("저장된 HTML 파일이 없습니다. 먼저 동화를 생성해 HTML로 저장해 주세요.")
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
            "열람할 파일을 선택하세요",
            options,
            index=default_index,
        )

        selected_path = exports[options.index(selection)]
        st.session_state["selected_export"] = str(selected_path)

        try:
            html_content = selected_path.read_text("utf-8")
        except Exception as exc:
            st.error(f"파일을 여는 데 실패했습니다: {exc}")
        else:
            st.download_button(
                "HTML 다운로드",
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
