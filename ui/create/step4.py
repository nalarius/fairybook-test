"""Step 4 view: select story or ending cards per stage."""
from __future__ import annotations

import os
import random

import streamlit as st
from streamlit_image_select import image_select

from app_constants import STAGE_GUIDANCE, STORY_PHASES
from session_state import (
    clear_stages_from,
    go_step,
    reset_all_state,
    reset_story_session,
)

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session
    story_cards = context.story_cards
    ending_cards = context.ending_cards
    illust_dir = context.illust_dir

    stage_idx = session.get("current_stage_idx", 0)
    if stage_idx >= len(STORY_PHASES):
        session["step"] = 6
        st.rerun()
        st.stop()

    stage_name = STORY_PHASES[stage_idx]
    card_instruction = "엔딩" if stage_name == STORY_PHASES[-1] else "이야기"
    st.subheader(f"4단계. {stage_name}에 어울리는 {card_instruction} 카드를 골라보세요")

    title_val = session.get("story_title")
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

    rand8 = session.get("rand8") or []
    if not rand8:
        st.warning("이야기 유형 데이터를 불러오지 못했습니다.")
        if st.button("처음으로 돌아가기", width='stretch'):
            reset_all_state()
            st.rerun()
            st.stop()
        st.stop()

    selected_type_idx = session.get("selected_type_idx", 0)
    if selected_type_idx >= len(rand8):
        selected_type_idx = max(0, len(rand8) - 1)
        session["selected_type_idx"] = selected_type_idx
    selected_type = rand8[selected_type_idx]

    age_val = session.get("age") or "6-8"
    topic_val = session.get("topic")
    topic_val = topic_val if topic_val is not None else ""
    topic_display = topic_val if topic_val else "(빈칸)"

    guidance = STAGE_GUIDANCE.get(stage_name)
    if guidance:
        st.caption(guidance)
    if is_final_stage:
        st.caption("엔딩 카드를 사용해 결말의 분위기를 골라보세요.")

    style_choice = session.get("story_style_choice")
    if style_choice and style_choice.get("name"):
        st.caption(f"삽화 스타일은 **{style_choice.get('name')}**로 유지됩니다.")

    previous_sections = [entry for entry in (session.get("stages_data") or [])[:stage_idx] if entry]
    if previous_sections:
        with st.expander("이전 단계 줄거리 다시 보기", expanded=False):
            for idx, entry in enumerate(previous_sections, start=1):
                stage_label = entry.get("stage") or f"단계 {idx}"
                st.markdown(f"**{stage_label}** — {entry.get('card', {}).get('name', '카드 미지정')}")
                for paragraph in entry.get("story", {}).get("paragraphs", []):
                    st.write(paragraph)

    cards = session.get("story_cards_rand4")
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
        session["story_cards_rand4"] = random.sample(available_cards, k=sample_size)
        session["selected_story_card_idx"] = 0
        cards = session.get("story_cards_rand4")

    selected_card_idx = session.get("selected_story_card_idx", 0)
    if selected_card_idx >= len(cards):
        selected_card_idx = max(0, len(cards) - 1)
        session["selected_story_card_idx"] = selected_card_idx
    selected_card = cards[selected_card_idx]

    st.markdown(f"**제목:** {title_val}")
    st.caption(
        f"나이대: **{age_val}** · 주제: **{topic_display}** · 이야기 유형: **{selected_type.get('name', '이야기 유형')}**"
    )
    st.caption("카드를 선택한 뒤 ‘이야기 만들기’ 버튼을 눌러주세요. 단계별로 생성된 내용은 자동으로 이어집니다.")

    card_images = [os.path.join(illust_dir, card.get("illust", "")) for card in cards]
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
        session["selected_story_card_idx"] = selected_idx
        selected_card = cards[selected_idx]

    card_prompt = (selected_card.get("prompt") or "").strip()
    card_label = "엔딩 카드" if is_final_stage else "이야기 카드"
    st.success(f"선택된 {card_label}: **{selected_card.get('name', card_label)}**")
    if card_prompt:
        st.caption(card_prompt)

    stages_data = session.get("stages_data") or []
    existing_stage = stages_data[stage_idx] if stage_idx < len(stages_data) else None
    if existing_stage:
        st.warning("이미 완성된 단계가 있어 새로 만들면 덮어씁니다.")

    if st.button("이 단계 이야기 만들기", type="primary", width='stretch'):
        reset_story_session(
            keep_title=True,
            keep_cards=True,
            keep_synopsis=True,
            keep_protagonist=True,
            keep_character=True,
            keep_style=True,
        )
        session["story_prompt"] = None
        session["is_generating_story"] = True
        session["step"] = 5
        st.rerun()
        st.stop()

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("← 제목 다시 만들기", width='stretch'):
            clear_stages_from(0)
            session["current_stage_idx"] = 0
            reset_story_session(
                keep_title=True,
                keep_cards=False,
                keep_synopsis=True,
                keep_protagonist=True,
                keep_character=True,
                keep_style=True,
            )
            go_step(2)
            st.rerun()
            st.stop()
    with nav_col2:
        if st.button("새로운 스토리 카드 뽑기", width='stretch'):
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

