"""Constants shared by the Streamlit admin tool."""
from __future__ import annotations

from typing import Final, Tuple

# Export limits and defaults
MAX_EXPORT_ROWS: Final[int] = 100_000
DEFAULT_DASHBOARD_RANGE_DAYS: Final[int] = 7
DEFAULT_PAGE_SIZE: Final[int] = 100

# Moderation enums kept in sync with activity logging docs
MODERATION_REASON_CODES: Tuple[str, ...] = (
    "spam",
    "abuse",
    "safety",
    "copyright",
    "user_request",
    "other",
)

MODERATION_TARGET_TYPES: Tuple[str, ...] = (
    "board_post",
    "board_comment",
    "story",
    "user_submission",
)

SANCTION_DURATION_PRESETS: Tuple[str, ...] = (
    "permanent",
    "24h",
    "7d",
    "30d",
)

__all__ = [
    "MAX_EXPORT_ROWS",
    "DEFAULT_DASHBOARD_RANGE_DAYS",
    "DEFAULT_PAGE_SIZE",
    "MODERATION_REASON_CODES",
    "MODERATION_TARGET_TYPES",
    "SANCTION_DURATION_PRESETS",
]
