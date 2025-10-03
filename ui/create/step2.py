"""Step 2 view: select story type and trigger initial generation."""
from __future__ import annotations

import os
import random
from datetime import datetime, timezone

import streamlit as st
from streamlit_image_select import image_select

from gemini_client import (
    build_character_image_prompt,
    build_image_prompt,
    generate_image_with_gemini,
    generate_protagonist_with_gemini,
    generate_synopsis_with_gemini,
    generate_title_with_gemini,
)
from session_state import (
    clear_stages_from,
    reset_all_state,
    reset_cover_art,
    reset_story_session,
)
from story_identifier import generate_story_id
from telemetry import emit_log_event

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session
    story_types = context.story_types
    illust_styles = context.illust_styles
    illust_dir = context.illust_dir

    st.subheader("2단계. 제목을 만들어보세요.")

    rand8 = session.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    selected_idx = session.get("selected_type_idx", 0)
    if selected_idx >= len(rand8):
        selected_idx = max(0, len(rand8) - 1)
    session["selected_type_idx"] = selected_idx
    selected_type = rand8[selected_idx]

    age_val = session.get("age") or "6-8"
    topic_val = session.get("topic")
    topic_val = topic_val if topic_val is not None else ""
    topic_display = topic_val if topic_val else "(빈칸)"
    type_prompt = (selected_type.get("prompt") or "").strip()
    story_type_name = selected_type.get("name", "이야기 유형")

    if session.get("is_generating_all"):
        st.header("동화의 씨앗을 심고 있어요 🌱")
        st.caption("이야기의 첫 단추를 꿰는 중입니다. 잠시만 기다려주세요.")
        progress_bar = st.progress(0.0, "시작하는 중...")

        def show_error_and_stop(message: str) -> None:
            st.error(message)
            session["is_generating_all"] = False
            if st.button("다시 시도하기", width='stretch'):
                reset_story_session()
                st.rerun()
            st.stop()

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
        session["synopsis_result"] = synopsis_text

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
        session["protagonist_result"] = protagonist_text

        progress_bar.progress(0.4, "삽화 스타일을 고르고 있어요...")
        if not illust_styles:
            show_error_and_stop("삽화 스타일을 찾을 수 없습니다. illust_styles.json을 확인해주세요.")
        style_choice = random.choice(illust_styles)
        session["story_style_choice"] = style_choice
        session["cover_image_style"] = style_choice
        session["selected_style_id"] = illust_styles.index(style_choice)

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
            session["character_prompt"] = char_prompt_data.get("prompt")
            char_image_resp = generate_image_with_gemini(char_prompt_data["prompt"])
            if "error" in char_image_resp:
                st.warning(f"주인공 설정화 생성 실패: {char_image_resp['error']}")
                session["character_image_error"] = char_image_resp["error"]
            else:
                session["character_image"] = char_image_resp.get("bytes")
                session["character_image_mime"] = char_image_resp.get("mime_type", "image/png")

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
        session["story_title"] = title_text

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
            use_reference_image=session.get("character_image") is not None,
        )
        if "error" in cover_prompt_data:
            st.warning(f"표지 프롬프트 생성 실패: {cover_prompt_data['error']}")
        else:
            session["cover_prompt"] = cover_prompt_data.get("prompt")
            cover_image_resp = generate_image_with_gemini(
                cover_prompt_data["prompt"],
                image_input=session.get("character_image"),
            )
            if "error" in cover_image_resp:
                st.warning(f"표지 이미지 생성 실패: {cover_image_resp['error']}")
                session["cover_image_error"] = cover_image_resp["error"]
            else:
                session["cover_image"] = cover_image_resp.get("bytes")
                session["cover_image_mime"] = cover_image_resp.get("mime_type", "image/png")

        progress_bar.progress(1.0, "완성! 다음 화면으로 이동합니다.")
        session["is_generating_all"] = False
        session.step = 3
        st.rerun()
        st.stop()

    st.caption("마음에 드는 이야기 유형 카드를 클릭한 뒤, '제목 만들기' 버튼을 눌러주세요.")
    type_images = [os.path.join(illust_dir, t.get("illust", "")) for t in rand8]
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
        session["selected_type_idx"] = sel_idx
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
        if not session.get("story_id"):
            started_at = datetime.now(timezone.utc)
            story_id, started_at_iso = generate_story_id(
                age=age_val,
                topic=topic_val,
                started_at=started_at,
            )
            session["story_id"] = story_id
            session["story_started_at"] = started_at_iso
            story_type_name_for_log = selected_type.get("name") if selected_type else None
            topic_display_for_log = topic_val if topic_val else "(빈칸)"
            emit_log_event(
                type="story",
                action="story start",
                result="success",
                params=[
                    story_id,
                    age_val,
                    story_type_name_for_log,
                    topic_display_for_log,
                    None,
                ],
            )
        session["is_generating_all"] = True
        st.rerun()
        st.stop()

    st.markdown("---")
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 이야기 아이디어 다시 입력", width='stretch'):
            reset_story_session()
            session.step = 1
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 유형 뽑기", width='stretch'):
            session["rand8"] = random.sample(story_types, k=min(8, len(story_types))) if story_types else []
            session["selected_type_idx"] = 0
            reset_story_session()
            st.rerun()
            st.stop()
    with nav_col3:
        if st.button("모두 초기화", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()

