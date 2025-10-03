"""Session state helpers for the Streamlit app."""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

try:  # pragma: no cover - allows importing without Streamlit in tests
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - test fallback
    from types import SimpleNamespace

    st = SimpleNamespace(session_state={})

from app_constants import STORY_PHASES
from session_proxy import StorySessionProxy


_STATE_DEFAULTS: dict[str, Any] = {
    # Flow & selection state
    "step": 0,
    "mode": None,
    "age": None,
    "topic": None,
    "story_id": None,
    "story_started_at": None,
    "view_story_id": None,
    "story_view_logged_token": None,
    "board_view_logged": False,
    "current_stage_idx": 0,
    "selected_type_idx": 0,
    "selected_story_card_idx": 0,
    "selected_style_id": None,

    # Form seed values
    "age_input": "6-8",
    "topic_input": "",

    # Board form state
    "board_user_alias": None,
    "board_content": "",
    "board_submit_error": None,
    "board_submit_success": None,

    # Authentication state
    "auth_user": None,
    "auth_error": None,
    "auth_form_mode": "signin",
    "auth_next_action": None,

    # UI helper flags
    "reset_inputs_pending": False,

    # Story generation artefacts
    "story_error": None,
    "story_result": None,
    "story_prompt": None,
    "story_image": None,
    "story_image_mime": "image/png",
    "story_image_style": None,
    "story_image_error": None,
    "story_cards_rand4": None,
    "story_card_choice": None,
    "story_export_path": None,
    "story_export_remote_url": None,
    "story_export_remote_blob": None,
    "selected_export": None,
    "story_export_signature": None,
    "story_style_choice": None,

    # Async flags
    "is_generating_synopsis": False,
    "is_generating_protagonist": False,
    "is_generating_character_image": False,
    "is_generating_title": False,
    "is_generating_story": False,
    "is_generating_all": False,

    # Synopsis & protagonist artefacts
    "synopsis_result": None,
    "synopsis_hooks": None,
    "synopsis_error": None,
    "protagonist_result": None,
    "protagonist_error": None,

    # Character art
    "character_prompt": None,
    "character_image": None,
    "character_image_mime": "image/png",
    "character_image_error": None,

    # Story output & title
    "story_title": None,
    "story_title_error": None,

    # Cover artefacts
    "cover_image": None,
    "cover_image_mime": "image/png",
    "cover_image_style": None,
    "cover_image_error": None,
    "cover_prompt": None,
}


def _proxy() -> StorySessionProxy:
    """Return a proxy around the current Streamlit session state."""

    return StorySessionProxy(st.session_state)


def ensure_state(story_types: Sequence[Mapping[str, Any]]) -> None:
    proxy = _proxy()
    for key, default in _STATE_DEFAULTS.items():
        proxy.setdefault(key, default)

    stages = proxy.get("stages_data")
    if not isinstance(stages, list) or len(stages) != len(STORY_PHASES):
        proxy["stages_data"] = [None] * len(STORY_PHASES)

    if "rand8" not in proxy and story_types:
        import random

        proxy["rand8"] = random.sample(story_types, k=min(8, len(story_types)))


def go_step(step: int) -> None:
    proxy = _proxy()
    proxy.step = step
    if step in (1, 2, 3, 4, 5, 6):
        proxy.mode = "create"


def clear_stages_from(index: int) -> None:
    proxy = _proxy()
    stages = proxy.get("stages_data")
    if not isinstance(stages, list):
        proxy["stages_data"] = [None] * len(STORY_PHASES)
        return

    for idx in range(index, len(STORY_PHASES)):
        if idx < len(stages):
            stages[idx] = None


def reset_character_art() -> None:
    proxy = _proxy()
    proxy.reset_keys(
        "character_prompt",
        "character_image",
        "character_image_error",
    )
    proxy["character_image_mime"] = "image/png"
    proxy.set_flag("is_generating_character_image", False)


def reset_cover_art(*, keep_style: bool = False) -> None:
    proxy = _proxy()
    proxy.reset_keys("cover_image", "cover_image_error", "cover_prompt")
    proxy["cover_image_mime"] = "image/png"
    if not keep_style:
        proxy["cover_image_style"] = None


def reset_title_and_cover(*, keep_style: bool = False, keep_title: bool = False) -> None:
    proxy = _proxy()
    if not keep_title:
        proxy["story_title"] = None
    proxy["story_title_error"] = None
    reset_cover_art(keep_style=keep_style)


def reset_protagonist_state(*, keep_style: bool = True) -> None:
    proxy = _proxy()
    proxy.reset_keys("protagonist_result", "protagonist_error")
    proxy.set_flag("is_generating_protagonist", False)
    if not keep_style:
        proxy.reset_keys("selected_style_id", "story_style_choice")


def reset_story_session(
    *,
    keep_title: bool = False,
    keep_cards: bool = False,
    keep_synopsis: bool = False,
    keep_protagonist: bool = False,
    keep_character: bool = False,
    keep_style: bool = False,
) -> None:
    proxy = _proxy()
    keys = {
        "story_error": None,
        "story_result": None,
        "story_prompt": None,
        "story_image": None,
        "story_image_mime": "image/png",
        "story_image_style": None,
        "story_image_error": None,
        "story_export_path": None,
        "story_export_remote_url": None,
        "story_export_remote_blob": None,
        "story_export_signature": None,
        "selected_export": None,
        "is_generating_story": False,
        "is_generating_title": False,
        "story_card_choice": None,
        "story_style_choice": None,
        "cover_image_style": None,
        "selected_style_id": None,
    }

    if not keep_synopsis:
        keys.update(
            {
                "synopsis_result": None,
                "synopsis_hooks": None,
                "synopsis_error": None,
                "is_generating_synopsis": False,
            }
        )
    if not keep_protagonist:
        keys.update(
            {
                "protagonist_result": None,
                "protagonist_error": None,
                "is_generating_protagonist": False,
            }
        )
    if not keep_character:
        keys.update(
            {
                "character_prompt": None,
                "character_image": None,
                "character_image_mime": "image/png",
                "character_image_error": None,
                "is_generating_character_image": False,
            }
        )
    if keep_style:
        keys.pop("selected_style_id", None)
        keys.pop("story_style_choice", None)
        keys.pop("cover_image_style", None)

    for key, value in keys.items():
        proxy[key] = value

    if not keep_title:
        proxy["story_title"] = None

    if not keep_cards:
        proxy["story_cards_rand4"] = None
        proxy["selected_story_card_idx"] = 0


def reset_all_state() -> None:
    proxy = _proxy()
    keys_to_clear: Iterable[str] = {
        "age",
        "topic",
        "story_id",
        "story_started_at",
        "view_story_id",
        "story_view_logged_token",
        "board_view_logged",
        "age_input",
        "topic_input",
        "rand8",
        "selected_type_idx",
        "current_stage_idx",
        "story_error",
        "story_result",
        "story_prompt",
        "story_image",
        "story_image_mime",
        "story_image_style",
        "story_image_error",
        "story_title",
        "story_title_error",
        "story_cards_rand4",
        "selected_story_card_idx",
        "story_card_choice",
        "story_export_path",
        "story_export_remote_url",
        "story_export_remote_blob",
        "story_export_signature",
        "selected_export",
        "is_generating_title",
        "is_generating_story",
        "is_generating_all",
        "stages_data",
        "story_style_choice",
        "cover_image",
        "cover_image_mime",
        "cover_image_style",
        "cover_image_error",
        "cover_prompt",
        "synopsis_result",
        "synopsis_hooks",
        "synopsis_error",
        "is_generating_synopsis",
        "protagonist_result",
        "protagonist_error",
        "is_generating_protagonist",
        "character_prompt",
        "character_image",
        "character_image_mime",
        "character_image_error",
        "is_generating_character_image",
        "selected_style_id",
    }

    for key in keys_to_clear:
        proxy.pop(key, None)

    proxy.mode = None
    proxy.step = 0


__all__ = [
    "ensure_state",
    "go_step",
    "clear_stages_from",
    "reset_character_art",
    "reset_cover_art",
    "reset_title_and_cover",
    "reset_protagonist_state",
    "reset_story_session",
    "reset_all_state",
    "StorySessionProxy",
]
