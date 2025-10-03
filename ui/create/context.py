"""Shared context objects for the create flow."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from session_proxy import StorySessionProxy


@dataclass(slots=True)
class CreatePageContext:
    session: StorySessionProxy
    story_types: list[dict]
    illust_styles: list[dict]
    story_cards: list[dict]
    ending_cards: list[dict]
    use_remote_exports: bool
    auth_user: Mapping[str, Any] | None
    home_background: str | None
    illust_dir: str


__all__ = ["CreatePageContext"]

