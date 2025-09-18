# app.py
import json, os, random
import streamlit as st
from story import generate_story, coerce_story_type
from streamlit_image_select import image_select

st.set_page_config(page_title="한 줄 동화 만들기", page_icon="📖", layout="centered")
st.title("📖 한 줄 주제로 동화 만들기 (텍스트만)")

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

# ---- 입력 ----
age = st.selectbox("나이대", ["6-8","9-12"], index=0)
topic = st.text_input("한 줄 주제(없으면 타입 기본 맥락 사용)", "")

st.markdown("### 이야기 유형을 골라주세요 (랜덤 8개 중 1개)")
st.caption("이미지를 클릭하면 하나만 선택됩니다. (eng_name, prompt는 표시하지 않음)")

# ---- 랜덤 8개 준비 (세션에 유지) ----
if "rand8" not in st.session_state:
    st.session_state.rand8 = random.sample(story_types, k=min(8, len(story_types)))
rand8 = st.session_state.rand8

# ---- 8장 썸네일을 한 번에 image_select로 전달 → 단일 선택 ----
image_paths = [os.path.join(ILLUST_DIR, t.illust) for t in rand8]
captions    = [t.name for t in rand8]

# 한 번만 호출! (여기서 하나만 선택됨)
selected_idx = image_select(
    label="",                   # 라벨 숨김
    images=image_paths,
    captions=captions,
    use_container_width=True,   # 가로 폭 채우기 → 화면 폭에 맞춰 4x2로 자동 줄바꿈
    return_value="index",
    key="rand8_picker"
)

# 선택 결과
selected_type = rand8[selected_idx] if selected_idx is not None else rand8[0]
st.success(f"선택된 이야기 유형: **{selected_type.name}**")

# ---- 생성 버튼 ----
if st.button("동화 만들기", type="primary", use_container_width=True):
    data = generate_story(age_band=age, story_type=selected_type, topic=(topic or None))
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

# ---- 새로 8개 뽑기 ----
if st.button("새로운 8개 뽑기"):
    st.session_state.rand8 = random.sample(story_types, k=min(8, len(story_types)))
    st.rerun()
