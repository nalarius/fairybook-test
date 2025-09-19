# app.py
import os, json, random
import streamlit as st
from streamlit_image_select import image_select
from gemini_client import generate_story_with_gemini

st.set_page_config(page_title="한 줄 동화 만들기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
ILLUST_DIR = "illust"

@st.cache_data
def load_story_types():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("story_types", [])

story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

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

ensure_state()

def go_step(n: int):
    st.session_state["step"] = n

# ─────────────────────────────────────────────────────────────────────
# 헤더/진행
# ─────────────────────────────────────────────────────────────────────
st.title("📖 한 줄 주제로 동화 만들기 (텍스트만)")
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

    # LLM 호출
    if st.button("동화 만들기", type="primary", use_container_width=True):
        with st.spinner("Gemini로 동화 생성 중..."):
            result = generate_story_with_gemini(
                age=age_val,
                topic=topic_val or None,
                story_type_name=selected_type["name"],
            )
        if "error" in result:
            st.error(f"생성 실패: {result['error']}")
        else:
            st.subheader(result["title"])
            for p in result["paragraphs"]:
                st.write(p)

            st.download_button(
                "텍스트 다운로드",
                data=result["title"] + "\n\n" + "\n".join(result["paragraphs"]),
                file_name="fairytale.txt",
                mime="text/plain",
                use_container_width=True
            )

    # 하단 버튼들
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 이전 단계로", use_container_width=True):
            # 이전 단계로만 이동. 값은 유지.
            go_step(1)
    with c2:
        if st.button("새로운 8개 뽑기", use_container_width=True):
            st.session_state["rand8"] = random.sample(story_types, k=min(8, len(story_types)))
            st.session_state["selected_type_idx"] = 0
            st.rerun()
    with c3:
        if st.button("모두 초기화", use_container_width=True):
            # 전체 초기화 후 1단계로
            for k in ["age", "topic", "age_input", "topic_input", "rand8", "selected_type_idx"]:
                st.session_state.pop(k, None)
            st.session_state["step"] = 1
            st.rerun()
