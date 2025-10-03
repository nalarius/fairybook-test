"""Styling helpers for Streamlit layouts."""
from __future__ import annotations

from typing import Optional

import streamlit as st


def render_app_styles(home_bg: Optional[str], *, show_home_hero: bool = False) -> None:
    """Apply global background styling and optionally render the home hero image."""
    base_css = """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f6f2ff 0%, #fff8f2 68%, #ffffff 100%);
    }
    [data-testid="stHeader"] {
        background: rgba(0, 0, 0, 0);
    }
    [data-testid="stAppViewContainer"] > .main > div:first-child {
        background-color: rgba(255, 255, 255, 0.9);
        border-radius: 20px;
        padding: 1.75rem 2rem;
        box-shadow: 0 18px 44px rgba(0, 0, 0, 0.12);
        backdrop-filter: blur(1.5px);
        max-width: 780px;
    }
    [data-testid="stAppViewContainer"] > .main > div:first-child h1 {
        margin-bottom: 0.2rem;
    }
    .home-hero {
        width: 100%;
        height: 570px;
        margin: 0.18rem 0 0.5rem;
        background-position: center;
        background-repeat: no-repeat;
        background-size: contain;
    }
    @media (max-width: 640px) {
        .home-hero {
            height: 360px;
            margin: 0.15rem 0 0.45rem;
        }
    }
    </style>
    """
    st.markdown(base_css, unsafe_allow_html=True)

    if show_home_hero and home_bg:
        st.markdown(
            f"<div class='home-hero' style='background-image: url(\"data:image/png;base64,{home_bg}\");'></div>",
            unsafe_allow_html=True,
        )
