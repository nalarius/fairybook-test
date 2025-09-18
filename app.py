# app.py
import json, os, random
import streamlit as st
from streamlit_image_select import image_select
from story import generate_story, coerce_story_type

st.set_page_config(page_title="한 줄 동화 만들기", page_icon="📖", layout="centered")

# ---------------------------
# 기본 설정 / 공용 로딩 함수
# ---------------------------
JSON_PATH = "storytype.json"
ILLUST_DIR = "illust"

@st.cache_data
def load_story_types():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [coerce_story_type(x) for x in raw.get("story_types", [])]

story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

# ---------------------------
# 세션 상태 초기화
# ---------------------------
if "step" not in st.session_state:
    st.session_state.step = 1  # 1: 입력, 2: 유형선택/생성
if "age" not in st.session_state:
    st.session_state.age = "6-8"
if "topic" not in st.session_state:
    st.session_state.topic = ""
if "rand8" not in st.session_state:
    st.session_state.rand8 = random.sample(story_types, k=min(8, len(story_types)))
if "selected_type_idx" not in st.session_state:
    st.session_state.selected_type_idx = 0  # rand8 내 인덱스

def go_step(n: int):
    st.session_state.step = n

# ---------------------------
# UI: 헤더
# ---------------------------
st.title("📖 한 줄 주제로 동화 만들기 (텍스트만)")
st.progress(0.5 if st.session_state.step == 1 else 1.0)
st.caption("간단한 2단계로 동화를 만들어보세요.")

# ---------------------------
# STEP 1 — 나이대 / 주제
# ---------------------------
if st.session_state.step == 1:
    st.subheader("1단계. 나이대와 주제를 고르세요")

    # ✅ key 바인딩: 위젯이 세션에 직접 기록/유지
    st.selectbox(
        "나이대",
        ["6-8", "9-12"],
        index=0 if st.session_state.age == "6-8" else 1,
        key="age",
    )

    st.text_input(
        "한 줄 주제(없으면 빈칸 OK)",
        placeholder="예) 잃어버린 모자를 찾기",
        key="topic",   # ✅ 핵심: 세션에 자동 저장됨
    )

    col1, col2 = st.columns([1,1])
    with col1:
        if st.button("다음 단계로 →", type="primary", use_container_width=True):
            # 다음 단계로 이동
            go_step(2)
    with col2:
        if st.button("입력 초기화", use_container_width=True):
            st.session_state.age = "6-8"
            st.session_state.topic = ""

# ---------------------------
# STEP 2 — 이야기 유형 선택 & 생성
# ---------------------------
elif st.session_state.step == 2:
    st.subheader("2단계. 이야기 유형을 고르세요")

    # 랜덤 8개(세션 유지)
    rand8 = st.session_state.rand8
    image_paths = [os.path.join(ILLUST_DIR, t.illust) for t in rand8]
    captions    = [t.name for t in rand8]

    st.caption("아래 썸네일 8개 중 하나를 클릭하세요. (한 줄에 4개씩 보이는 형태)")
    selected_idx = image_select(
        label="",
        images=image_paths,
        captions=captions,
        use_container_width=True,
        return_value="index",
        key="rand8_picker"
    )

    # 선택 상태 반영 (클릭 없으면 기존 선택 유지)
    if selected_idx is not None:
        st.session_state.selected_type_idx = selected_idx

    selected_type = rand8[st.session_state.selected_type_idx]

    # ✅ 표시/생성 시 세션 값을 직접 참조
    st.success(f"선택된 이야기 유형: **{selected_type.name}**")
    st.write(
        f"나이대: **{st.session_state.get('age', '6-8')}**, "
        f"주제: **{(st.session_state.get('topic') or '(빈칸)')}**"
    )

    # 동화 생성 버튼
    if st.button("동화 만들기", type="primary", use_container_width=True):
        data = generate_story(
            age_band=st.session_state.age,
            story_type=selected_type,
            topic=(st.session_state.topic or None)
        )
        st.subheader(data["title"])
        for p in data["paragraphs"]:
            st.write(p)

        st.download_button(
            "텍스트 다운로드",
            data=data["title"] + "\n\n" + "\n".join(data["paragraphs"]),
            file_name="fairytale.txt",
            mime="text/plain",
            use_container_width=True
        )

    # 하단 버튼들
    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        if st.button("← 이전 단계로", use_container_width=True):
            go_step(1)
    with c2:
        if st.button("새로운 8개 뽑기", use_container_width=True):
            st.session_state.rand8 = random.sample(story_types, k=min(8, len(story_types)))
            st.session_state.selected_type_idx = 0
            st.rerun()
    with c3:
        if st.button("모두 초기화", use_container_width=True):
            # 전체 초기화 후 1단계로
            for k in ["age","topic","rand8","selected_type_idx"]:
                st.session_state.pop(k, None)
            st.session_state.step = 1
            st.rerun()
