"""Step 5 view: generate story stage content and illustrations."""
from __future__ import annotations

import random

import streamlit as st

from app_constants import STORY_PHASES
from gemini_client import build_image_prompt, generate_image_with_gemini, generate_story_with_gemini
from session_state import (
    clear_stages_from,
    go_step,
    reset_all_state,
    reset_story_session,
)
from telemetry import emit_log_event

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session
    illust_styles = context.illust_styles

    stage_idx = session.get("current_stage_idx", 0)
    if stage_idx >= len(STORY_PHASES):
        session["step"] = 6
        st.rerun()
        st.stop()

    stage_name = STORY_PHASES[stage_idx]
    st.subheader(f"4단계. {stage_name} 이야기를 확인하세요")

    title_val = session.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", width='stretch'):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    cards = session.get("story_cards_rand4")
    if not cards:
        st.warning("이야기 카드를 다시 선택해주세요.")
        if st.button("이야기 카드 화면으로", width='stretch'):
            go_step(4)
            st.rerun()
            st.stop()
        st.stop()

    rand8 = session.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    age_val = session.get("age") or "6-8"
    topic_val = session.get("topic")
    topic_val = topic_val if topic_val is not None else ""
    topic_display = topic_val if topic_val else "(빈칸)"
    selected_type = rand8[session.get("selected_type_idx", 0)]

    selected_card_idx = session.get("selected_story_card_idx", 0)
    if selected_card_idx >= len(cards):
        selected_card_idx = max(0, len(cards) - 1)
        session["selected_story_card_idx"] = selected_card_idx
    selected_card = cards[selected_card_idx]
    card_name = selected_card.get("name", "이야기 카드")
    card_prompt = (selected_card.get("prompt") or "").strip()

    previous_sections = []
    for entry in (session.get("stages_data") or [])[:stage_idx]:
        if not entry:
            continue
        previous_sections.append(
            {
                "stage": entry.get("stage"),
                "card_name": entry.get("card", {}).get("name"),
                "paragraphs": entry.get("story", {}).get("paragraphs", []),
            }
        )

    if session.get("is_generating_story"):
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
                synopsis_text=session.get("synopsis_result"),
                protagonist_text=session.get("protagonist_result"),
            )

            if "error" in story_result:
                error_message = story_result.get("error")
                action_name = "story end" if stage_idx == len(STORY_PHASES) - 1 else "story card"
                emit_log_event(
                    type="story",
                    action=action_name,
                    result="fail",
                    params=[
                        session.get("story_id"),
                        card_name,
                        stage_name,
                        None,
                        error_message,
                    ],
                )
                session["story_error"] = error_message
                session["story_result"] = None
                session["story_prompt"] = None
                session["story_image"] = None
                session["story_image_error"] = None
                session["story_image_style"] = None
                session["story_image_mime"] = "image/png"
                session["story_card_choice"] = None
            else:
                story_payload = dict(story_result)
                story_payload["title"] = title_val.strip() if title_val else story_payload.get("title", "")
                session["story_error"] = None
                session["story_result"] = story_payload
                session["story_card_choice"] = {
                    "name": card_name,
                    "prompt": card_prompt,
                    "stage": stage_name,
                }

                style_choice = session.get("story_style_choice")
                if not style_choice and illust_styles:
                    fallback_style = random.choice(illust_styles)
                    style_choice = {
                        "name": fallback_style.get("name"),
                        "style": fallback_style.get("style"),
                    }
                    session["story_style_choice"] = style_choice
                elif not style_choice:
                    session["story_error"] = "삽화 스타일을 불러오지 못했습니다. illust_styles.json을 확인해주세요."
                    session["story_result"] = story_payload
                    session["story_prompt"] = None
                    session["story_image"] = None
                    session["story_image_error"] = "삽화 스타일이 없어 생성을 중단했습니다."
                    session["story_image_style"] = None
                    session["story_image_mime"] = "image/png"
                    session["is_generating_story"] = False
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
                    protagonist_text=session.get("protagonist_result"),
                )

                if "error" in prompt_data:
                    session["story_prompt"] = None
                    session["story_image_error"] = prompt_data["error"]
                    session["story_image_style"] = None
                    session["story_image"] = None
                    session["story_image_mime"] = "image/png"
                else:
                    session["story_prompt"] = prompt_data["prompt"]
                    style_info = {
                        "name": prompt_data.get("style_name") or (style_choice or {}).get("name"),
                        "style": prompt_data.get("style_text") or (style_choice or {}).get("style"),
                    }
                    session["story_image_style"] = style_info
                    session["story_style_choice"] = style_info

                    image_response = generate_image_with_gemini(
                        prompt_data["prompt"],
                        image_input=session.get("character_image"),
                    )
                    if "error" in image_response:
                        session["story_image_error"] = image_response["error"]
                        session["story_image"] = None
                        session["story_image_mime"] = "image/png"
                    else:
                        session["story_image_error"] = None
                        session["story_image"] = image_response.get("bytes")
                        session["story_image_mime"] = image_response.get("mime_type", "image/png")

                stages_copy = list(session.get("stages_data") or [None] * len(STORY_PHASES))
                while len(stages_copy) < len(STORY_PHASES):
                    stages_copy.append(None)
                stages_copy[stage_idx] = {
                    "stage": stage_name,
                    "card": {
                        "name": card_name,
                        "prompt": card_prompt,
                    },
                    "story": story_payload,
                    "image_bytes": session.get("story_image"),
                    "image_mime": session.get("story_image_mime"),
                    "image_style": session.get("story_image_style"),
                    "image_prompt": session.get("story_prompt"),
                    "image_error": session.get("story_image_error"),
                }
                session["stages_data"] = stages_copy
                action_name = "story end" if stage_idx == len(STORY_PHASES) - 1 else "story card"
                emit_log_event(
                    type="story",
                    action=action_name,
                    result="success",
                    params=[
                        session.get("story_id"),
                        card_name,
                        stage_name,
                        None,
                        None,
                    ],
                )

        session["is_generating_story"] = False
        st.rerun()
        st.stop()

    story_error = session.get("story_error")
    stages_data = session.get("stages_data") or []
    stage_entry = stages_data[stage_idx] if stage_idx < len(stages_data) else None
    story_data = stage_entry.get("story") if stage_entry else session.get("story_result")

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
                session["story_error"] = None
                session["is_generating_story"] = True
                st.rerun()
                st.stop()
        with card_col:
            if st.button("카드 다시 고르기", width='stretch'):
                clear_stages_from(stage_idx)
                reset_story_session(
                    keep_title=True,
                    keep_cards=False,
                    keep_synopsis=True,
                    keep_protagonist=True,
                    keep_character=True,
                    keep_style=True,
                )
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

    image_bytes = stage_entry.get("image_bytes") if stage_entry else session.get("story_image")
    image_error = stage_entry.get("image_error") if stage_entry else session.get("story_image_error")

    if image_bytes:
        st.image(image_bytes, caption="AI 생성 삽화", width='stretch')
    elif image_error:
        st.warning(f"삽화 생성 실패: {image_error}")

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 카드 다시 고르기", width='stretch'):
            clear_stages_from(stage_idx)
            reset_story_session(
                keep_title=True,
                keep_cards=False,
                keep_synopsis=True,
                keep_protagonist=True,
                keep_character=True,
                keep_style=True,
            )
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
                session["current_stage_idx"] = stage_idx + 1
                reset_story_session(
                    keep_title=True,
                    keep_cards=False,
                    keep_synopsis=True,
                    keep_protagonist=True,
                    keep_character=True,
                    keep_style=True,
                )
                go_step(4)
                st.rerun()
                st.stop()
        else:
            if st.button(
                "이야기 모아보기 →",
                width='stretch',
                disabled=not stage_completed,
            ):
                session["step"] = 6
                reset_story_session(
                    keep_title=True,
                    keep_cards=False,
                    keep_synopsis=True,
                    keep_protagonist=True,
                    keep_character=True,
                    keep_style=True,
                )
                st.rerun()
                st.stop()
    with nav_col3:
        if st.button("모두 초기화", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()

    if stage_entry and stage_idx < len(STORY_PHASES) - 1:
        if st.button("이야기 모아보기", width='stretch'):
            session["step"] = 6
            st.rerun()
            st.stop()

