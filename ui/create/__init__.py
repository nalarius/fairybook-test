"""Helpers for orchestrating the create flow steps."""
from __future__ import annotations

from .context import CreatePageContext
from . import step1, step2, step3, step4, step5, step6


_STEP_RENDERERS = {
    1: step1.render_step,
    2: step2.render_step,
    3: step3.render_step,
    4: step4.render_step,
    5: step5.render_step,
    6: step6.render_step,
}


def render_current_step(context: CreatePageContext, step_number: int) -> None:
    renderer = _STEP_RENDERERS.get(step_number)
    if renderer is None:
        return
    renderer(context)


__all__ = ["CreatePageContext", "render_current_step"]

