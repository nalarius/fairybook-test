"""Telemetry helpers around the activity log module."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st

from activity_log import log_event
from utils.auth import auth_email


def emit_log_event(
    *,
    type: str,
    action: str,
    result: str,
    params: Sequence[str | None] | None = None,
    client_ip: str | None = None,
    user_email: str | None = None,
) -> Any:
    """Wrapper around ``log_event`` that defaults user_id to the current email."""

    auth_user_state = st.session_state.get("auth_user")
    derived_email = user_email if user_email is not None else auth_email(auth_user_state)  # type: ignore[arg-type]

    return log_event(
        type=type,
        action=action,
        result=result,
        user_id=derived_email,
        params=params,
        client_ip=client_ip,
    )


__all__ = ["emit_log_event"]
