"""Step 1 view: collect age range and topic ideas."""
from __future__ import annotations

import streamlit as st

from session_state import clear_stages_from, reset_cover_art, reset_story_session

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session

    st.subheader("1단계. 나이대와 이야기 아이디어를 입력하세요")

    if session.pop("reset_inputs_pending", False):
        session["age_input"] = "6-8"
        session["topic_input"] = ""

    with st.form("step1_form", clear_on_submit=False):
        st.selectbox(
            "나이대",
            ["6-8", "9-12"],
            index=0 if session["age_input"] == "6-8" else 1,
            key="age_input",
        )
        st.caption("이야기의 주제, 진행 방향, 주요 인물 등을 자유롭게 입력해주세요.")
        st.text_area(
            "이야기 아이디어",
            placeholder="예) 꼬마 제이가 동물 친구들과 함께 잃어버린 모자를 찾는 모험 이야기",
            height=96,
            key="topic_input",
        )
        c1, c2 = st.columns(2)
        go_next = c1.form_submit_button("다음 단계로 →", width='stretch')
        do_reset = c2.form_submit_button("입력 초기화", width='stretch')

    if do_reset:
        session["reset_inputs_pending"] = True
        st.rerun()

    if go_next:
        reset_story_session(keep_title=False, keep_cards=False)
        clear_stages_from(0)
        reset_cover_art()
        session["current_stage_idx"] = 0
        session["age"] = session["age_input"]
        session["topic"] = (session["topic_input"] or "").strip()
        session["story_id"] = None
        session["story_started_at"] = None
        session.step = 2

