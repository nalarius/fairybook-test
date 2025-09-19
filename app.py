# app.py
import base64
import html
import json
import os
import random
import re
from datetime import datetime

import streamlit as st
from streamlit_image_select import image_select
from gemini_client import generate_story_with_gemini, generate_image_with_gemini

st.set_page_config(page_title="한 줄 동화 만들기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
STYLE_JSON_PATH = "illust_styles.json"
ILLUST_DIR = "illust"
HTML_EXPORT_DIR = "html_exports"

os.makedirs(HTML_EXPORT_DIR, exist_ok=True)

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

story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

illust_styles = load_illust_styles()

# ─────────────────────────────────────────────────────────────────────
# 세션 상태: '없을 때만' 기본값. 절대 무조건 대입하지 않음.
# ─────────────────────────────────────────────────────────────────────
def ensure_state():
    st.session_state.setdefault("step", 1)                 # 1: 입력, 2: 유형/생성
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
    st.session_state.setdefault("story_export_path", None)

ensure_state()

def go_step(n: int):
    st.session_state["step"] = n


def build_illustration_prompt(story: dict, style: dict, *, age: str, topic: str | None, story_type: str) -> str:
    """생성된 동화 본문과 스타일 가이드를 이용해 이미지 프롬프트 생성."""
    paragraphs = story.get("paragraphs", [])
    summary = " ".join(paragraphs)[:900]
    topic_text = topic if topic else "자유 주제"
    return (
        f"Create a single vivid children's picture book illustration.\n"
        f"Audience age group: {age}.\n"
        f"Story type cue: {story_type}.\n"
        f"Story topic: {topic_text}.\n"
        f"Follow this art direction: {style.get('style', '').strip()}.\n"
        f"Key story beats to depict: {summary}.\n"
        "Frame the main characters with warm lighting and make the scene gentle, hopeful, and safe for young readers."
    )


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
    os.makedirs(HTML_EXPORT_DIR, exist_ok=True)

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
    export_path = os.path.join(HTML_EXPORT_DIR, filename)

    with open(export_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    return export_path

# ─────────────────────────────────────────────────────────────────────
# 헤더/진행
# ─────────────────────────────────────────────────────────────────────
st.title("📖 한 줄 주제로 동화 만들기")
st.progress(0.5 if st.session_state["step"] == 1 else 1.0)
st.caption("간단한 2단계로 동화를 만들어보세요.")

# ─────────────────────────────────────────────────────────────────────
# STEP 1 — 나이대/주제 입력 (form으로 커밋 시점 고정, 확정 키와 분리)
# ─────────────────────────────────────────────────────────────────────
if st.session_state["step"] == 1:
    st.subheader("1단계. 나이대와 주제를 고르세요")

    # 폼 제출 전까지는 age/topic을 건드리지 않음
    with st.form("step1_form", clear_on_submit=False):
        st.selectbox(
            "나이대",
            ["6-8", "9-12"],
            index=0 if st.session_state["age_input"] == "6-8" else 1,
            key="age_input",  # 위젯은 age_input에만 바인딩
        )
        st.text_input(
            "한 줄 주제(없으면 빈칸 OK)",
            placeholder="예) 잃어버린 모자를 찾기",
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
# STEP 2 — 이야기 유형 선택 + 생성
# ─────────────────────────────────────────────────────────────────────
elif st.session_state["step"] == 2:
    st.subheader("2단계. 이야기 유형을 고르세요")

    rand8 = st.session_state["rand8"]
    image_paths = [os.path.join(ILLUST_DIR, t["illust"]) for t in rand8]
    captions    = [t["name"] for t in rand8]

    st.caption("아래 썸네일 8개 중 하나를 클릭하세요. (한 줄에 4개씩 보이는 형태)")
    sel_idx = image_select(
        label="",
        images=image_paths,
        captions=captions,
        use_container_width=True,
        return_value="index",
        key="rand8_picker"  # 이미지만 선택(soft rerun) — 다른 상태는 건드리지 않음
    )
    if sel_idx is not None:
        st.session_state["selected_type_idx"] = sel_idx

    selected_type = rand8[st.session_state["selected_type_idx"]]

    # STEP1에서 '확정된 값'만 읽는다 (위젯 재바인딩 절대 금지)
    age_val   = st.session_state["age"] if st.session_state["age"] else "6-8"
    topic_val = st.session_state["topic"] if (st.session_state["topic"] is not None) else ""

    st.success(f"선택된 이야기 유형: **{selected_type['name']}**")
    st.write(f"나이대: **{age_val}**, 주제: **{topic_val if topic_val else '(빈칸)'}**")

    if not illust_styles:
        st.info("illust_styles.json을 찾지 못해 삽화는 생성되지 않습니다.")

    # 스토리 + 삽화 생성
    if st.button("동화 만들기", type="primary", use_container_width=True):
        st.session_state["story_error"] = None
        st.session_state["story_result"] = None
        st.session_state["story_prompt"] = None
        st.session_state["story_image"] = None
        st.session_state["story_image_error"] = None
        st.session_state["story_image_style"] = None
        st.session_state["story_export_path"] = None

        with st.spinner("Gemini로 동화 생성 중..."):
            result = generate_story_with_gemini(
                age=age_val,
                topic=topic_val or None,
                story_type_name=selected_type["name"],
            )

        if "error" in result:
            st.session_state["story_error"] = result["error"]
        else:
            st.session_state["story_result"] = result
            chosen_style = random.choice(illust_styles) if illust_styles else None
            st.session_state["story_image_style"] = chosen_style

            if not chosen_style:
                st.session_state["story_image_error"] = "illust_styles.json에서 사용할 스타일을 찾지 못했습니다."
            else:
                prompt = build_illustration_prompt(
                    story=result,
                    style=chosen_style,
                    age=age_val,
                    topic=topic_val,
                    story_type=selected_type["name"],
                )
                st.session_state["story_prompt"] = prompt

                with st.spinner("Gemini로 삽화 생성 중..."):
                    image_response = generate_image_with_gemini(prompt)

                if "error" in image_response:
                    st.session_state["story_image_error"] = image_response["error"]
                else:
                    st.session_state["story_image"] = image_response.get("bytes")
                    st.session_state["story_image_mime"] = image_response.get("mime_type", "image/png")

    if st.session_state.get("story_error"):
        st.error(f"생성 실패: {st.session_state['story_error']}")

    story_data = st.session_state.get("story_result")
    if story_data:
        st.subheader(story_data["title"])
        for p in story_data["paragraphs"]:
            st.write(p)

        st.download_button(
            "텍스트 다운로드",
            data=story_data["title"] + "\n\n" + "\n".join(story_data["paragraphs"]),
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
                    story_type=selected_type["name"],
                    style_name=style_info.get("name") if style_info else None,
                )
                st.session_state["story_export_path"] = export_path
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

    # 하단 버튼들
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 이전 단계로", use_container_width=True):
            # 이전 단계로만 이동. 값은 유지.
            go_step(1)
    with c2:
        if st.button("새로운 8개 뽑기", use_container_width=True):
            for k in [
                "story_error",
                "story_result",
                "story_prompt",
                "story_image",
                "story_image_mime",
                "story_image_style",
                "story_image_error",
                "story_export_path",
            ]:
                st.session_state.pop(k, None)
            st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types)))
            st.session_state["selected_type_idx"] = 0
            st.rerun()
    with c3:
        if st.button("모두 초기화", use_container_width=True):
            # 전체 초기화 후 1단계로
            for k in [
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
                "story_export_path",
            ]:
                st.session_state.pop(k, None)
            st.session_state["step"] = 1
            st.rerun()
