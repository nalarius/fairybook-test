# app.py
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import streamlit as st
import streamlit.components.v1 as components
from streamlit_image_select import image_select

from activity_log import init_activity_log
from app_constants import STAGE_GUIDANCE, STORY_PHASES
from gemini_client import (
    build_character_image_prompt,
    build_image_prompt,
    generate_image_with_gemini,
    generate_protagonist_with_gemini,
    generate_story_with_gemini,
    generate_synopsis_with_gemini,
    generate_title_with_gemini,
)
from gcs_storage import download_gcs_export, is_gcs_available, list_gcs_exports
from services.story_service import (
    ExportResult,
    HTML_EXPORT_PATH,
    StagePayload,
    StoryBundle,
    export_story_to_html,
    list_html_exports,
)
from session_state import (
    clear_stages_from,
    ensure_state,
    go_step,
    reset_all_state,
    reset_character_art,
    reset_cover_art,
    reset_protagonist_state,
    reset_story_session,
    reset_title_and_cover,
)
from story_identifier import generate_story_id
from story_library import StoryRecord, init_story_library, list_story_records, record_story_export
from telemetry import emit_log_event
from ui.auth import render_auth_gate
from ui.board import render_board_page
from ui.home import render_home_screen
from ui.styles import render_app_styles
from utils.auth import (
    auth_display_name,
    auth_email,
    clear_auth_session,
    ensure_active_auth_session,
)
from utils.network import get_client_ip
from utils.time_utils import format_kst

st.set_page_config(page_title="동화책 생성기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
STYLE_JSON_PATH = "illust_styles.json"
STORY_JSON_PATH = "story.json"
ENDING_JSON_PATH = "ending.json"
ILLUST_DIR = "illust"
HOME_BACKGROUND_IMAGE_PATH = Path("assets/illus-home-hero.png")

STORY_STORAGE_MODE_RAW = (os.getenv("STORY_STORAGE_MODE") or "remote").strip().lower()
if STORY_STORAGE_MODE_RAW in {"remote", "gcs"}:
    STORY_STORAGE_MODE = "remote"
else:
    STORY_STORAGE_MODE = "local"

USE_REMOTE_EXPORTS = STORY_STORAGE_MODE == "remote"
STORY_LIBRARY_INIT_ERROR: str | None = None
try:
    init_story_library()
except Exception as exc:  # pragma: no cover - initialization failure surfaced later
    STORY_LIBRARY_INIT_ERROR = str(exc)

init_activity_log()


def _load_json_entries_from_file(path: str | Path, key: str) -> list[dict]:
    """Safely load a list of dict entries from a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    items = payload.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]

@st.cache_data
def load_story_types():
    return _load_json_entries_from_file(JSON_PATH, "story_types")

@st.cache_data
def load_illust_styles():
    return _load_json_entries_from_file(STYLE_JSON_PATH, "illust_styles")


@st.cache_data
def load_story_cards():
    return _load_json_entries_from_file(STORY_JSON_PATH, "cards")


@st.cache_data
def load_ending_cards():
    return _load_json_entries_from_file(ENDING_JSON_PATH, "story_endings")


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

ensure_state(story_types)



def logout_user() -> None:
    previous_user = st.session_state.get("auth_user")
    display_name = None
    user_email = None
    if isinstance(previous_user, Mapping):
        display_name = auth_display_name(previous_user)
        user_email = auth_email(previous_user)
    client_ip = get_client_ip()
    clear_auth_session()
    reset_all_state()
    st.session_state["board_user_alias"] = None
    st.session_state["board_content"] = ""
    st.session_state["auth_next_action"] = None
    emit_log_event(
        type="user",
        action="logout",
        result="success",
        params=[client_ip, display_name, None, None, None],
        client_ip=client_ip,
        user_email=user_email,
    )
# ─────────────────────────────────────────────────────────────────────
# 헤더/인증/진행
# ─────────────────────────────────────────────────────────────────────
home_bg = load_image_as_base64(str(HOME_BACKGROUND_IMAGE_PATH))
auth_user = ensure_active_auth_session()
mode = st.session_state.get("mode")
current_step = st.session_state["step"]

if mode in {"create", "board"} and not auth_user:
    st.session_state["auth_next_action"] = mode
    st.session_state["mode"] = "auth"
    st.rerun()

if mode == "auth":
    render_auth_gate(home_bg)
    st.stop()

st.title("📖 동화책 생성기")
header_cols = st.columns([6, 1])

with header_cols[0]:
    if auth_user:
        st.caption(f"👋 **{auth_display_name(auth_user)}**님 반가워요.")
    else:
        st.caption("로그인하면 동화 만들기와 게시판을 이용할 수 있어요.")

with header_cols[1]:
    menu = st.popover("⚙️", width='stretch')
    with menu:
        st.markdown("#### 메뉴")
        if auth_user:
            st.write(f"현재 사용자: **{auth_display_name(auth_user)}**")
            if st.button("로그아웃", width='stretch'):
                logout_user()
                st.rerun()
            st.button("설정 (준비중)", disabled=True, width='stretch')
            st.caption("설정 항목은 준비 중이에요.")
        else:
            if st.button("로그인 / 회원가입", width='stretch'):
                st.session_state["auth_next_action"] = None
                st.session_state["mode"] = "auth"
                st.session_state["auth_form_mode"] = "signin"
                st.session_state["auth_error"] = None
                st.rerun()
            st.button("설정 (로그인 필요)", disabled=True, width='stretch')
            st.caption("로그인하면 더 많은 기능을 사용할 수 있어요.")

progress_placeholder = st.empty()


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

if mode != "board":
    if current_step == 0:
        st.caption("원하는 작업을 선택해주세요.")
    elif mode == "create":
        st.caption("차근차근 동화를 완성해보세요.")
    else:
        st.caption("저장된 동화를 살펴볼 수 있어요.")

# ─────────────────────────────────────────────────────────────────────
# STEP 1 — 나이대/주제 입력 (form으로 커밋 시점 고정, 확정 키와 분리)
# ─────────────────────────────────────────────────────────────────────
if mode == "board":
    render_board_page(home_bg, auth_user=auth_user)
    st.stop()

render_app_styles(home_bg, show_home_hero=current_step == 0)

if current_step == 0:
    render_home_screen(
        auth_user=auth_user,
        use_remote_exports=USE_REMOTE_EXPORTS,
        story_types=story_types,
    )

elif current_step == 1:
    st.subheader("1단계. 나이대와 이야기 아이디어를 입력하세요")

    if st.session_state.pop("reset_inputs_pending", False):
        st.session_state["age_input"] = "6-8"
        st.session_state["topic_input"] = ""

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
        go_next = c1.form_submit_button("다음 단계로 →", width='stretch')
        do_reset = c2.form_submit_button("입력 초기화", width='stretch')

    if do_reset:
        # 임시 위젯 값만 초기화. 확정값(age/topic)은 건드리지 않음.
        st.session_state["reset_inputs_pending"] = True
        st.rerun()

    if go_next:
        # 이 시점에만 확정 키로 복사
        reset_story_session(keep_title=False, keep_cards=False)
        clear_stages_from(0)
        reset_cover_art()
        st.session_state["current_stage_idx"] = 0
        st.session_state["age"] = st.session_state["age_input"]
        st.session_state["topic"] = (st.session_state["topic_input"] or "").strip()
        st.session_state["story_id"] = None
        st.session_state["story_started_at"] = None
        st.session_state["step"] = 2

elif current_step == 2:
    st.subheader("2단계. 제목을 만들어보세요.")

    rand8 = st.session_state["rand8"]
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
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
            if st.button("다시 시도하기", width='stretch'):
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

    if st.button("✨ 제목 만들기", type="primary", width='stretch'):
        reset_story_session()
        if not st.session_state.get("story_id"):
            started_at = datetime.now(timezone.utc)
            story_id, started_at_iso = generate_story_id(
                age=age_val,
                topic=topic_val,
                started_at=started_at,
            )
            st.session_state["story_id"] = story_id
            st.session_state["story_started_at"] = started_at_iso
            story_type_name_for_log = selected_type.get("name") if selected_type else None
            topic_display = topic_val if topic_val else "(빈칸)"
            emit_log_event(
                type="story",
                action="story start",
                result="success",
                params=[story_id, age_val, story_type_name_for_log, topic_display, None],
            )
        st.session_state["is_generating_all"] = True
        st.rerun()
        st.stop()

    st.markdown("---")
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 이야기 아이디어 다시 입력", width='stretch'):
            reset_story_session()
            go_step(1)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 유형 뽑기", width='stretch'):
            st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types))) if story_types else []
            st.session_state["selected_type_idx"] = 0
            reset_story_session()
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", width='stretch'):
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
        if st.button("제목 만들기 화면으로 돌아가기", width='stretch'):
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
        st.image(cover_image, caption=caption, width='stretch')
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
        st.image(character_image, caption=caption, width='stretch')
    elif character_error:
        st.warning(f"설정화 생성 실패: {character_error}")
    else:
        st.info("설정화가 아직 없습니다. 2단계에서 스타일을 선택하고 생성해 주세요.")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 제목 다시 만들기", width='stretch'):
            reset_story_session()
            go_step(2)
            st.rerun()
            st.stop()

    with c2:
        if st.button("모두 초기화", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()

    with c3:
        continue_disabled = not title_val
        if st.button("계속해서 이야기 만들기 →", type="primary", width='stretch', disabled=continue_disabled):
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
    st.subheader(f"4단계. {stage_name}에 어울리는 {card_instruction} 카드를 골라보세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", width='stretch'):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    is_final_stage = stage_name == STORY_PHASES[-1]
    available_cards = ending_cards if is_final_stage else story_cards

    if not available_cards:
        missing_msg = "ending.json" if is_final_stage else "story.json"
        st.error(f"{missing_msg}에서 사용할 수 있는 이야기 카드를 찾지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    rand8 = st.session_state.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
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
        st.caption("엔딩 카드를 사용해 결말의 분위기를 골라보세요.")

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
            if st.button("처음으로 돌아가기", width='stretch'):
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

    if st.button("이 단계 이야기 만들기", type="primary", width='stretch'):
        reset_story_session(keep_title=True, keep_cards=True, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
        st.session_state["story_prompt"] = None
        st.session_state["is_generating_story"] = True
        st.session_state["step"] = 5
        st.rerun()
        st.stop()

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 제목 다시 만들기", width='stretch'):
            clear_stages_from(0)
            st.session_state["current_stage_idx"] = 0
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            go_step(2)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 카드 뽑기", width='stretch'):
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", width='stretch'):
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
    st.subheader(f"4단계. {stage_name} 이야기를 확인하세요")

    title_val = st.session_state.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", width='stretch'):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    cards = st.session_state.get("story_cards_rand4")
    if not cards:
        st.warning("이야기 카드를 다시 선택해주세요.")
        if st.button("이야기 카드 화면으로", width='stretch'):
            go_step(4)
            st.rerun()
            st.stop()
        st.stop()

    rand8 = st.session_state.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
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
                error_message = story_result.get("error")
                action_name = "story end" if stage_idx == len(STORY_PHASES) - 1 else "story card"
                emit_log_event(
                    type="story",
                    action=action_name,
                    result="fail",
                    params=[
                        st.session_state.get("story_id"),
                        card_name,
                        stage_name,
                        None,
                        error_message,
                    ],
                )
                st.session_state["story_error"] = error_message
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
                    use_reference_image=False,
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
                action_name = "story end" if stage_idx == len(STORY_PHASES) - 1 else "story card"
                emit_log_event(
                    type="story",
                    action=action_name,
                    result="success",
                    params=[
                        st.session_state.get("story_id"),
                        card_name,
                        stage_name,
                        None,
                        None,
                    ],
                )

        st.session_state["is_generating_story"] = False
        st.rerun()
        st.stop()

    story_error = st.session_state.get("story_error")
    stages_data = st.session_state.get("stages_data") or []
    stage_entry = stages_data[stage_idx] if stage_idx < len(stages_data) else None
    story_data = stage_entry.get("story") if stage_entry else st.session_state.get("story_result")

    if not story_data and not story_error:
        st.info("이야기 카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요.")
        if st.button("이야기 카드 화면으로", width='stretch'):
            go_step(4)
            st.rerun()
            st.stop()
        st.stop()

    if story_error:
        st.error(f"이야기 생성 실패: {story_error}")
        retry_col, card_col, reset_col = st.columns(3)
        with retry_col:
            if st.button("다시 시도", width='stretch'):
                st.session_state["story_error"] = None
                st.session_state["is_generating_story"] = True
                st.rerun()
                st.stop()
        with card_col:
            if st.button("카드 다시 고르기", width='stretch'):
                clear_stages_from(stage_idx)
                reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
                go_step(4)
                st.rerun()
                st.stop()
        with reset_col:
            if st.button("모두 초기화", width='stretch'):
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
        st.image(image_bytes, caption="AI 생성 삽화", width='stretch')
    elif image_error:
        st.warning(f"삽화 생성 실패: {image_error}")

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 카드 다시 고르기", width='stretch'):
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
                width='stretch',
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
                width='stretch',
                disabled=not stage_completed,
            ):
                st.session_state["step"] = 6
                reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
                st.rerun()
                st.stop()
    with nav_col3:
        if st.button("모두 초기화", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()

    if stage_entry and stage_idx < len(STORY_PHASES) - 1:
        if st.button("이야기 모아보기", width='stretch'):
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

        if st.button("남은 단계 이어가기 →", width='stretch'):
            st.session_state["current_stage_idx"] = next_stage_idx
            reset_story_session(keep_title=True, keep_cards=False, keep_synopsis=True, keep_protagonist=True, keep_character=True, keep_style=True)
            st.session_state["step"] = 4
            st.rerun()
        st.stop()


    cover_image = st.session_state.get("cover_image")
    cover_error = st.session_state.get("cover_image_error")
    cover_style = st.session_state.get("story_style_choice") or st.session_state.get("cover_image_style")

    export_ready_stages: list[StagePayload] = []
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
            StagePayload(
                stage_name=stage_name,
                card_name=card_info.get("name"),
                card_prompt=card_info.get("prompt"),
                paragraphs=paragraphs,
                image_bytes=image_bytes,
                image_mime=entry.get("image_mime") or "image/png",
                image_style_name=(entry.get("image_style") or {}).get("name"),
            )
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
            bundle = StoryBundle(
                title=title_val,
                stages=export_ready_stages,
                synopsis=st.session_state.get("synopsis_result"),
                protagonist=st.session_state.get("protagonist_result"),
                cover=cover_payload,
                story_type_name=story_type_name,
                age=age_val,
                topic=topic_val,
            )
            export_result = export_story_to_html(
                bundle=bundle,
                author=auth_display_name(auth_user) if auth_user else None,
                use_remote_exports=USE_REMOTE_EXPORTS,
            )
            st.session_state["story_export_path"] = export_result.local_path
            st.session_state["story_export_signature"] = signature
            if USE_REMOTE_EXPORTS:
                st.session_state["story_export_remote_url"] = export_result.gcs_url
                st.session_state["story_export_remote_blob"] = export_result.gcs_object
                if export_result.gcs_object:
                    st.session_state["selected_export"] = f"gcs:{export_result.gcs_object}"
                else:
                    st.session_state["selected_export"] = export_result.local_path
            else:
                st.session_state["story_export_remote_url"] = None
                st.session_state["story_export_remote_blob"] = None
                st.session_state["selected_export"] = export_result.local_path
            auto_saved = True
            user_email = auth_email(auth_user)
            emit_log_event(
                type="story",
                action="story save",
                result="success",
                params=[
                    st.session_state.get("story_id"),
                    title_val,
                    export_result.gcs_object or export_result.local_path,
                    export_result.gcs_url,
                    "auto-save",
                ],
                user_email=user_email,
            )
            if auth_user:
                try:
                    record_story_export(
                        user_id=str(auth_user.get("uid", "")),
                        title=title_val,
                        local_path=export_result.local_path,
                        gcs_object=export_result.gcs_object,
                        gcs_url=export_result.gcs_url,
                        story_id=st.session_state.get("story_id"),
                        author_name=auth_display_name(auth_user),
                    )
                except Exception as exc:  # pragma: no cover - display only
                    emit_log_event(
                        type="story",
                        action="story save",
                        result="fail",
                        params=[
                            st.session_state.get("story_id"),
                            title_val,
                            export_result.gcs_object or export_result.local_path,
                            export_result.gcs_url,
                            str(exc),
                        ],
                        user_email=user_email,
                    )
                    st.warning(f"동화 기록을 저장하지 못했어요: {exc}")
        except Exception as exc:
            emit_log_event(
                type="story",
                action="story save",
                result="fail",
                params=[
                    st.session_state.get("story_id"),
                    title_val,
                    None,
                    None,
                    str(exc),
                ],
            )
            st.error(f"HTML 자동 저장 실패: {exc}")

    export_path_current = st.session_state.get("story_export_path")
    remote_url_current = st.session_state.get("story_export_remote_url")
    if auto_saved:
        if USE_REMOTE_EXPORTS:
            if remote_url_current:
                st.success("HTML 저장 및 GCS 업로드를 완료했어요.")
                st.caption(f"원격 URL: {remote_url_current}")
            else:
                st.warning("GCS 업로드에 실패했습니다. 로컬 파일만 저장되었어요.")
                if export_path_current:
                    st.caption(f"로컬 파일: {export_path_current}")
        elif export_path_current:
            st.success(f"HTML 자동 저장 완료: {export_path_current}")

    st.markdown(f"### {title_val}")
    if cover_image:
        st.image(cover_image, width='stretch')
    elif cover_error:
        st.caption("표지 일러스트를 준비하지 못했어요.")

    last_export = st.session_state.get("story_export_path")
    last_remote = st.session_state.get("story_export_remote_url")

    for idx, section in enumerate(display_sections):
        if section.get("missing"):
            st.warning("이야기 단계가 비어 있습니다. 다시 생성해 주세요.")
            continue

        image_bytes = section.get("image_bytes")
        image_error = section.get("image_error")
        paragraphs = section.get("paragraphs") or []

        if image_bytes:
            st.image(image_bytes, width='stretch')
        elif image_error:
            st.caption("삽화를 준비하지 못했어요.")

        for paragraph in paragraphs:
            st.write(paragraph)

        if idx < len(display_sections) - 1:
            st.markdown("---")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 첫 화면으로", width='stretch'):
            reset_all_state()
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", width='stretch'):
            reset_all_state()
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.rerun()
    with c3:
        if st.button("📂 저장한 동화 보기", width='stretch'):
            st.session_state["mode"] = "view"
            st.session_state["step"] = 5
            st.rerun()

elif current_step == 5 and mode == "view":
    st.subheader("저장한 동화 보기")
    if STORY_LIBRARY_INIT_ERROR:
        st.warning(f"동화 기록 저장소 초기화 중 문제가 발생했어요: {STORY_LIBRARY_INIT_ERROR}")
    filter_options = ["모두의 동화"]
    if auth_user:
        filter_options.append("내 동화")

    view_filter = st.radio(
        "어떤 동화를 살펴볼까요?",
        filter_options,
        horizontal=True,
        key="story_view_filter",
    )
    if not auth_user:
        st.caption("로그인하면 내가 만든 동화만 모아볼 수 있어요.")

    records: list[StoryRecord] | None = None
    records_error: str | None = None
    try:
        if view_filter == "내 동화" and auth_user:
            records = list_story_records(user_id=str(auth_user.get("uid")), limit=100)
        else:
            records = list_story_records(limit=100)
    except Exception as exc:  # pragma: no cover - defensive catch
        records_error = str(exc)
        records = []

    if records_error:
        st.error(f"동화 기록을 불러오지 못했어요: {records_error}")

    entries: list[dict[str, Any]] = []
    recorded_keys: set[str] = set()

    for record in records:
        key_candidate = (record.gcs_object or record.local_path or record.html_filename or "").lower()
        if key_candidate:
            recorded_keys.add(key_candidate)
        entries.append(
            {
                "token": f"record:{record.id}",
                "title": record.title,
                "author": record.author_name,
                "story_id": record.story_id,
                "created_at": record.created_at_utc,
                "local_path": record.local_path,
                "gcs_object": record.gcs_object,
                "gcs_url": record.gcs_url,
                "html_filename": record.html_filename,
                "origin": "record",
            }
        )

    include_legacy = view_filter != "내 동화"
    if include_legacy:
        legacy_candidates: list[Any] = []
        if USE_REMOTE_EXPORTS:
            if is_gcs_available():
                legacy_candidates = list_gcs_exports()
        else:
            legacy_candidates = list_html_exports()

        for item in legacy_candidates:
            if USE_REMOTE_EXPORTS:
                key = (item.object_name or item.filename).lower()
                if key in recorded_keys:
                    continue
                created_at = item.updated
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                created_at = created_at or datetime.fromtimestamp(0, tz=timezone.utc)
                entries.append(
                    {
                        "token": f"legacy-remote:{item.object_name}",
                        "title": Path(item.filename).stem,
                        "author": None,
                        "created_at": created_at,
                        "local_path": None,
                        "gcs_object": item.object_name,
                        "gcs_url": item.public_url,
                        "html_filename": item.filename,
                        "origin": "legacy-remote",
                    }
                )
            else:
                key = str(item).lower()
                if key in recorded_keys:
                    continue
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                except Exception:
                    mtime = datetime.fromtimestamp(0, tz=timezone.utc)
                entries.append(
                    {
                        "token": f"legacy-local:{item}",
                        "title": item.stem,
                        "author": None,
                        "created_at": mtime,
                        "local_path": str(item),
                        "gcs_object": None,
                        "gcs_url": None,
                        "html_filename": item.name,
                        "origin": "legacy-local",
                    }
                )

    if not entries:
        if view_filter == "내 동화":
            st.info("아직 내가 만든 동화가 없어요. 새 동화를 만들어보세요.")
        else:
            st.info("저장된 동화가 없습니다. 먼저 동화를 생성해주세요.")
    else:
        entries.sort(key=lambda entry: entry.get("created_at", datetime.fromtimestamp(0, tz=timezone.utc)), reverse=True)

        def _format_entry(idx: int) -> str:
            entry = entries[idx]
            created = entry.get("created_at")
            stamp = format_kst(created) if created else "시간 정보 없음"
            author = entry.get("author")
            if author and view_filter != "내 동화":
                return f"{entry['title']} · {author} · {stamp}"
            return f"{entry['title']} · {stamp}"

        tokens = [entry["token"] for entry in entries]
        selected_token = st.session_state.get("selected_export")
        default_index = 0
        if selected_token in tokens:
            default_index = tokens.index(selected_token)

        selected_index = st.selectbox(
            "읽고 싶은 동화를 선택하세요",
            list(range(len(entries))),
            index=default_index,
            format_func=_format_entry,
            key="story_entry_select",
        )

        selected_entry = entries[selected_index]
        st.session_state["selected_export"] = selected_entry["token"]
        st.session_state["view_story_id"] = selected_entry.get("story_id")
        st.session_state["story_export_remote_blob"] = selected_entry.get("gcs_object")
        st.session_state["story_export_remote_url"] = selected_entry.get("gcs_url")

        html_content: str | None = None
        html_error: str | None = None
        local_candidates: list[Path] = []

        local_path = selected_entry.get("local_path")
        if local_path:
            local_candidates.append(Path(local_path))
        html_filename = selected_entry.get("html_filename")
        if html_filename:
            local_candidates.append(HTML_EXPORT_PATH / html_filename)

        for candidate in local_candidates:
            try:
                if candidate.exists():
                    html_content = candidate.read_text("utf-8")
                    st.session_state["story_export_path"] = str(candidate)
                    break
            except Exception as exc:
                html_error = str(exc)

        if html_content is None and selected_entry.get("gcs_object"):
            html_content = download_gcs_export(selected_entry["gcs_object"])
            if html_content is None:
                html_error = "원격 저장소에서 파일을 불러오지 못했어요."

        token = selected_entry["token"]
        story_origin = selected_entry.get("origin")
        story_title_display = selected_entry.get("title")
        story_id_value = selected_entry.get("story_id")

        if html_content is None:
            if html_error:
                st.error(f"동화를 여는 데 실패했습니다: {html_error}")
            else:
                st.error("동화를 여는 데 실패했습니다.")
            if selected_entry.get("gcs_url"):
                st.caption(f"파일 URL: {selected_entry['gcs_url']}")
            elif local_path:
                st.caption(f"파일 경로: {local_path}")
            log_key = f"fail:{token}"
            if st.session_state.get("story_view_logged_token") != log_key:
                emit_log_event(
                    type="story",
                    action="story view",
                    result="fail",
                    params=[
                        story_id_value or token,
                        story_title_display,
                        story_origin,
                        selected_entry.get("gcs_url") or local_path,
                        html_error or "missing content",
                    ],
                )
                st.session_state["story_view_logged_token"] = log_key
        else:
            st.download_button(
                "동화 다운로드",
                data=html_content,
                file_name=selected_entry.get("html_filename") or "story.html",
                mime="text/html",
                width='stretch',
            )
            if selected_entry.get("gcs_url"):
                st.caption(f"파일 URL: {selected_entry['gcs_url']}")
            elif local_path:
                st.caption(f"파일 경로: {local_path}")
            components.html(html_content, height=700, scrolling=True)
            log_key = f"success:{token}"
            if st.session_state.get("story_view_logged_token") != log_key:
                emit_log_event(
                    type="story",
                    action="story view",
                    result="success",
                    params=[
                        story_id_value or token,
                        story_title_display,
                        story_origin,
                        selected_entry.get("gcs_url") or local_path,
                        None,
                    ],
                )
                st.session_state["story_view_logged_token"] = log_key

    c1, c2 = st.columns(2)
    with c1:
        if st.button("← 선택 화면으로", width='stretch'):
            st.session_state["mode"] = None
            st.session_state["step"] = 0
            st.session_state["selected_export"] = None
            st.session_state["story_export_path"] = None
            st.session_state["view_story_id"] = None
            st.session_state["story_view_logged_token"] = None
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", width='stretch'):
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.session_state["story_view_logged_token"] = None
            st.session_state["view_story_id"] = None
            st.rerun()
