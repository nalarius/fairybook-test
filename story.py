# story.py
from dataclasses import dataclass
import random, re
from typing import List, Dict, Any

@dataclass
class StoryType:
    id: int
    name: str
    eng_name: str
    prompt: str
    illust_prompt: str
    illust: str

def coerce_story_type(d: Dict[str, Any]) -> StoryType:
    return StoryType(
        id=int(d.get("id")),
        name=str(d.get("name", "")),
        eng_name=str(d.get("eng_name", "")),
        prompt=str(d.get("prompt", "")),
        illust_prompt=str(d.get("illust_prompt", "")),
        illust=str(d.get("illust", "")),
    )

def generate_story(age_band: str, story_type: StoryType, topic: str | None = None):
    """
    age_band: "6-8" | "9-12"
    story_type: JSON에서 선택된 타입(이미지 카드로 고름)
    topic: 한 줄 주제 (없으면 기본값)
    """
    WORD_LIMIT = {"6-8": {"len": 12, "paras": 8}, "9-12": {"len": 18, "paras": 10}}

    # 스토리 타입에 따라 분위기 레이블 간단 매핑(문장 톤 결정에 사용)
    ADVENTURE_LIKE = {"adventure","fantasy","peril","journey","friend","courage"}
    tone_label = "adventure" if story_type.eng_name.lower() in ADVENTURE_LIKE else "warm"
    OPENERS = {
        "warm": ["어느 맑은 아침,", "햇살이 포근하던 날,"],
        "adventure": ["바람이 분 날,", "구름이 빠르게 흐르던 날,"],
    }

    topic = (topic or f"{story_type.name} 주제의 작은 이야기").strip()
    topic = re.sub(r"[^\w\s가-힣]", "", topic)
    conf = WORD_LIMIT[age_band]
    opener = random.choice(OPENERS[tone_label])

    # 제목은 타입 이름 + 주제 혼합
    title = f"{story_type.name}: {topic}"

    # 스토리 타입 설명(story_type.prompt)을 ‘문맥 힌트’로 사용
    hint = story_type.prompt.strip()
    if hint:
        hint = re.sub(r"\s+", " ", hint)

    # 8~10단락 기본 골자(연령에 따라 자르기)
    outline = [
        "주인공과 배경 소개",
        "작은 사건의 시작",
        "친구/도움 등장",
        "실마리 발견",
        "갈등 혹은 장애",
        "용기/지혜로 해결",
        "따뜻한 마무리",
        "교훈 한 줄",
        "보너스 에필로그",   # 9–12세에서만 나올 수 있음
        "끝인사",           # 9–12세에서만 나올 수 있음
    ][:conf["paras"]]

    # 시드 문장을 타입 힌트/주제를 녹여서 단순 생성
    seeds_base = [
        f"{opener} 이 이야기는 {story_type.name}을(를) 바탕으로 합니다",
        f"주인공의 마음에는 {topic}에 대한 바람이 살짝 피어납니다",
        f"친구가 손을 잡고 함께 해보자고 말합니다",
        "작은 단서를 발견하고 모두 눈을 반짝입니다",
        "뜻대로 되지 않지만 모두 포기하지 않습니다",
        "서로를 돕자 길이 조금씩 열립니다",
        "마침내 마음이 원하는 곳에 닿습니다",
        "오늘 배운 것은 서로를 믿고 천천히 나아가는 용기입니다",
        f"{story_type.name} 이야기는 여기서 잠시 숨을 고릅니다",
        "고맙다는 인사를 전하며 이야기를 마칩니다",
    ]

    # 간단 문장화(길이 제한 + 마침표 보정)
    def make_sentence(txt: str) -> str:
        # 스토리 타입 prompt(힌트)를 일부 문장에 살짝 끼워 넣어 ‘느낌’만 부여
        if hint and random.random() < 0.35:
            txt += f" ({story_type.eng_name}: {hint.split(' ')[0]} …)"
        txt = txt[:conf["len"]]
        txt = re.sub(r"[,.!?]+$", "", txt)
        return txt + "입니다."

    paragraphs = [make_sentence(seeds_base[i]) for i in range(len(outline))]
    return {"title": title, "paragraphs": paragraphs}
