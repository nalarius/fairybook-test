"""Prototype StorySession proxy for wrapping Streamlit session state.

This module is *not* wired into the app yet. It exists to validate the
interface we want before introducing it to production code. The proxy presents a
minimal mapping-style API while exposing typed helpers for common fields.
"""
from __future__ import annotations

from session_proxy import StorySessionProxy


__all__ = ["StorySessionProxy"]
