"""Step 3 view: confirm title, synopsis, and cover."""
from __future__ import annotations

import streamlit as st

from session_state import clear_stages_from, go_step, reset_all_state, reset_story_session

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session

    st.subheader("3단계. 완성된 제목과 표지를 확인해보세요")

    title_val = session.get("story_title")
    if not title_val:
        st.warning("제목을 먼저 생성해야 합니다.")
        if st.button("제목 만들기 화면으로 돌아가기", width='stretch'):
            go_step(2)
            st.rerun()
            st.stop()
        st.stop()

    cover_image = session.get("cover_image")
    cover_error = session.get("cover_image_error")
    cover_style = session.get("cover_image_style") or session.get("story_style_choice")
    synopsis_text = session.get("synopsis_result")
    protagonist_text = session.get("protagonist_result")
    character_image = session.get("character_image")
    character_error = session.get("character_image_error")
    style_choice = session.get("story_style_choice")

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
        if st.button(
            "계속해서 이야기 만들기 →",
            type="primary",
            width='stretch',
            disabled=continue_disabled,
        ):
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
            session["step"] = 4
            st.rerun()
            st.stop()

