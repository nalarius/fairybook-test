"""Story prompt assembly helpers for Gemini calls."""
from __future__ import annotations

import json
from typing import Iterable, Mapping


STAGE_GUIDANCE: Mapping[str, str] = {
    "발단": "주인공과 배경, 출발 계기를 선명하게 보여주고 모험의 씨앗을 심어 주세요. 따뜻함과 호기심이 함께 느껴지도록 합니다.",
    "전개": "주요 갈등과 사건을 키우며 인물들의 선택을 드러내세요. 긴장감과 숨 돌릴 따뜻한 순간이 번갈아 나오도록 합니다.",
    "위기": "가장 큰 위기와 감정의 파고를 그려주세요. 위험과 두려움 속에서도 서로의 믿음이나 재치가 빛날 틈을 남깁니다.",
    "절정": "결정적인 행동과 극적인 전환을 보여주세요. 장엄하거나 아슬아슬한 분위기 속에서 감정이 폭발하도록 합니다.",
    "결말": "사건의 여파를 정리하며 여운을 남기세요. 밝거나 씁쓸한 결말 모두 가능하며, 다음 상상을 부르는 여백을 둡니다.",
}


def get_stage_guidance() -> Mapping[str, str]:
    return dict(STAGE_GUIDANCE)


def build_title_prompt(
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    synopsis_text: str | None = None,
    protagonist_text: str | None = None,
) -> str:
    topic_clean = (topic or "").strip()
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미생성)"
    protagonist_block = (protagonist_text or "").strip() or "(주인공 설정 미생성)"

    return f"""당신은 어린이를 위한 동화 작가입니다.
입력으로 나이대, 주제, 이야기 유형, 시놉시스, 주인공 정보가 주어집니다.
이 정보를 활용하여 동화의 분위기와 핵심 갈등을 담은 **인상적인 한국어 제목**을 하나 만들어 주세요.

- **반드시 하나의 최종 제목만 생성해야 합니다.** 두 개 이상의 제목을 이어서 붙이지 마세요.
- 밝은 모험과 서늘한 긴장이 교차할 수 있음을 반영하고, 따뜻한 장면이나 유머의 여지도 남겨두세요.
- 결말을 특정 방향으로 단정 짓지 말고, 행복한 끝과 씁쓸한 끝 모두 가능하다는 여운을 살려주세요.
- 감정을 단조롭게 만들지 말고 장면이 떠오르는 단어로 분위기를 암시하세요.
- 한국 독자가 익숙한 자연스러운 표현을 사용하고, 문장은 간결하면서도 임팩트 있게 구성하세요.
- 제목은 25자 이내로 작성하며 구두점을 사용하지 않습니다.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
- 시놉시스: {synopsis_block}
- 주인공 설명: {protagonist_block}

[출력 형식]
{{
  "title": "제목"
}}
"""


def build_synopsis_prompt(
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
) -> str:
    topic_clean = (topic or "").strip()
    return f"""당신은 어린이 그림책 기획을 맡은 시니어 편집자입니다. 입력으로 나이대, 주제, 이야기 유형 설명이 주어집니다. 이 정보를 토대로 동화의 토대가 되는 간단한 시놉시스를 작성하세요.
- 밝은 모험과 서늘한 긴장이 공존하되, 숨 돌릴 수 있는 따뜻한 순간도 포함하세요.
- 결말을 특정 방향으로 고정하지 말고 열린 여운을 남기세요.
- **결과는 반드시 한 문단의 평문으로만 작성하고, 절대로 불릿, 번호 목록, JSON 형식 등을 사용하지 마세요.**
- 문장 수는 3~5문장, 자연스러운 한국어 흐름으로 구성하세요.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
"""


def build_protagonist_prompt(
    *,
    age: str,
    topic: str | None,
    story_type_name: str,
    story_type_prompt: str,
    synopsis_text: str | None,
) -> str:
    topic_clean = (topic or "").strip()
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미생성)"
    return f"""당신은 어린이 동화의 캐릭터 디자이너입니다. 입력으로 한 동화의 나이대, 주제, 이야기 유형, 간단한 시놉시스가 주어집니다. 이 동화의 주인공의 상세 설정을 **한 문단의 평문으로만** 작성하세요.

- 주인공의 이름, 정체성, 성격, 목표, 외형적 특징, 상징적인 소품 등을 자연스럽게 엮어 하나의 이야기처럼 묘사합니다.
- 주인공이 겪는 위기와 성장 동기를 분명히 제시하되, 한쪽 감정에 치우치지 마세요.
- 밝은 모험과 서늘한 긴장감이 공존하도록 성격과 행동을 설계하고, 숨 돌릴 따뜻한 면모나 익살스러운 특징도 드러내세요.
- 외형·복장·상징 소품을 구체적으로 묘사하되 잔혹한 표현은 피하세요.
- **결과는 반드시 한 문단의 평문으로만 작성하고, 절대로 불릿, 번호 목록, JSON 형식 등을 사용하지 마세요.**
- 문장은 3~5개 사이의 자연스러운 한국어로 구성합니다.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 이야기 유형: {story_type_name}
- 이야기 유형 설명: {story_type_prompt.strip()}
- 시놉시스: {synopsis_block}
"""


def build_story_prompt(
    *,
    age: str,
    topic: str | None,
    title: str,
    story_type_name: str,
    stage_name: str,
    stage_index: int,
    total_stages: int,
    story_card_name: str,
    story_card_prompt: str,
    previous_sections: list[dict] | None,
    synopsis_text: str | None = None,
    protagonist_text: str | None = None,
) -> str:
    topic_clean = (topic or "").strip()
    safe_title = json.dumps(title.strip(), ensure_ascii=False) if title else '"동화"'
    stage_number = stage_index + 1
    total_count = max(total_stages, stage_number)
    stage_label = stage_name or f"{stage_number}단계"
    stage_focus = STAGE_GUIDANCE.get(
        stage_name,
        "이번 단계의 극적 역할을 명확하게 드러내며 사건과 감정을 전개하세요.",
    )

    previous_sections = previous_sections or []
    summary_lines: list[str] = []
    for item in previous_sections:
        label = item.get("stage") or item.get("stage_name") or f"단계 {len(summary_lines) + 1}"
        card_name = item.get("card_name") or item.get("card")
        paragraphs = item.get("paragraphs") or []
        merged = " ".join(str(p).strip() for p in paragraphs if str(p).strip())
        merged = merged[:600] if merged else "(간단한 요약이 없습니다)"
        if card_name:
            label = f"{label} ({card_name})"
        summary_lines.append(f"{label}: {merged}")

    if summary_lines:
        previous_block = "\n".join(f"- {line}" for line in summary_lines)
    else:
        previous_block = "- 아직 작성된 단계가 없습니다."

    card_prompt_clean = (story_card_prompt or "").strip() or "(설명 없음)"
    synopsis_block = (synopsis_text or "").strip() or "(시놉시스 미제공)"
    protagonist_block = (protagonist_text or "").strip() or "(주인공 미제공)"

    return f"""당신은 어린이를 위한 연속 동화 작가입니다.
이 동화는 총 {total_count}단계 구조(발단-전개-위기-절정-결말)로 진행되며, 지금은 {stage_number}단계 "{stage_label}"을 작성합니다.
앞선 단계들의 분위기와 인과를 이어가면서, 이번 단계만의 극적 역할을 분명히 하세요.

[전체 이야기 설정]
- 시놉시스: {synopsis_block}
- 주인공: {protagonist_block}

[이전 단계 요약]
{previous_block}

[이번 단계 카드]
- 카드 이름: {story_card_name}
- 카드 설명: {card_prompt_clean}

[작성 지침]
- {stage_focus}
- **주인공 설정과 시놉시스를 충실히 반영하여** 이전 단계와 자연스럽게 이어지도록 사건과 감정의 흐름을 조율하세요.
- 감정과 상황은 인물의 행동, 대사, 표정, 호흡, 몸짓, 주변 환경 묘사로 보여 주고, 단정적인 설명은 줄이세요. 필요하면 내적 독백과 미세한 감각 변화를 통해 심리를 드러내세요.
- 밝은 순간과 서늘한 긴장감이 공존하도록 하고, 모험 속 위기와 숨 돌릴 유머나 따뜻함을 함께 담으세요.
- 반전이나 정체성 전환은 한국어식 표현이나 대사로 드러내고, 영어식 문장 구조를 사용하지 마세요.
- 시각·청각·후각·촉각·미각 등 오감을 활용해 장면의 공기와 질감을 생생하게 전달하세요.
- 문장은 간결하고 임팩트 있게 구성하되, 자연스럽고 인간적인 한국어 리듬을 유지하세요.
- 결말을 강요하지 말고 다양한 감정의 선택지를 열어 두되, 이번 단계가 전체 서사의 탄탄한 디딤돌이 되도록 하세요.
- 나이대에 맞는 어휘와 리듬을 사용하고, 주제를 인물의 행동과 상징에 자연스럽게 녹여 주세요.
- 장면 묘사, 인물의 감정, 대화를 균형 있게 배치해 아이가 장면을 선명하게 상상할 수 있도록 하세요.

[출력 형식]
{{
  "title": {safe_title},
  "paragraphs": ["첫 번째 단락", "두 번째 단락"]
}}
- JSON 이외의 설명이나 주석을 붙이지 마세요.
- "paragraphs" 리스트는 정확히 2개의 단락을 담습니다. 각 단락은 2~3문장으로 작성해 리듬감 있게 전개하세요.

[입력]
- 나이대: {age}
- 주제: {topic_clean if topic_clean else "(빈칸)"}
- 제목: {title.strip()}
- 이야기 유형: {story_type_name}
- 현재 단계: {stage_label} (총 {total_count}단계 중 {stage_number}단계)
- 이야기 카드 이름: {story_card_name}
- 이야기 카드 설명: {card_prompt_clean}
"""


def _traits_block(style_text: str) -> str:
    fragments = [fragment.strip() for fragment in style_text.split(",") if fragment.strip()]
    if not fragments:
        return "- Warm, friendly picture book aesthetic"
    return "\n".join(f"- {fragment}" for fragment in fragments)


def build_image_prompt_text(
    *,
    story_title: str,
    story_paragraphs: Iterable[str],
    age: str,
    topic: str | None,
    story_type_name: str,
    story_card_name: str | None,
    stage_name: str | None,
    style_name: str,
    style_text: str,
    is_character_sheet: bool = False,
    use_reference_image: bool = False,
    protagonist_text: str | None = None,
) -> str:
    topic_text = (topic or "").strip() or "(빈칸)"
    summary = " ".join(str(p).strip() for p in story_paragraphs if str(p).strip())
    summary = summary[:1500]

    character_sheet_directive = ""
    if is_character_sheet:
        character_sheet_directive = """
- **This is a character sheet.** The image must feature the main character only.
- The background must be a solid, plain, clean white background.
- The character should be in a neutral, full-body pose.
- Do not include any shadows, text, or other elements. Just the character.
"""

    reference_image_directive = ""
    if use_reference_image:
        reference_image_directive = (
            "\n- **The provided reference image depicts the story's protagonist. Center the cover around this exact character.**"
            "\n- **Crucially, the protagonist described below MUST strictly match the provided character reference image.** Depict the character as shown in the reference image, adapting their pose, wardrobe, and features faithfully while placing them in the new scene described in the summary."
        )

    protagonist_block = f"\n- Protagonist Description: {protagonist_text}" if protagonist_text else ""
    traits_block = _traits_block(style_text)

    return f"""You are an art director and text-to-image prompt engineer for a children's picture book. Analyze the given story plot and style references to write a prompt for generating **a single illustration** in English. Faithfully capture the unique mood of the style to allow young readers to experience new emotions.

[Story]
- Title: {story_title or "(Untitled)"}
- Age Group: {age}
- Topic: {topic_text}
- Story Type: {story_type_name}
- Narrative Card: {story_card_name or "(Not selected)"}
- Stage: {stage_name or "(Not specified)"}
- Summary: {summary}{protagonist_block}

[Style Reference]
- Illustrator: {style_name}
- Descriptor: {style_text}
- Style Traits:\n{traits_block}

[Requirements]
- The final output must be a single paragraph of a pure English prompt (no bullets or explanations).
- It must include the phrase "in the style of {style_name}".
- It must incorporate the expressions listed in the Style Traits above, connecting them naturally with the scene description.
- Describe the main characters, key events, background, emotions, lighting, and color palette in detail.
- Prioritize recreating the mood and emotion required by the style; do not force it to be cute or safe.
- Include "without text, typography, signature, or watermark" in the generation prompt to ensure no text, logos, or signs appear.{character_sheet_directive}{reference_image_directive}
"""


__all__ = [
    "STAGE_GUIDANCE",
    "get_stage_guidance",
    "build_title_prompt",
    "build_synopsis_prompt",
    "build_protagonist_prompt",
    "build_story_prompt",
    "build_image_prompt_text",
]

