# app.py
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import streamlit as st
import streamlit.components.v1 as components

from activity_log import init_activity_log
from app_constants import STORY_PHASES
from gcs_storage import download_gcs_export, is_gcs_available, list_gcs_exports
from services.story_service import HTML_EXPORT_PATH, export_story_to_html, list_html_exports
from session_state import (
    clear_stages_from,
    ensure_state,
    go_step,
    reset_all_state,
    reset_character_art,
    reset_cover_art,
    reset_protagonist_state,
    reset_story_session,
    reset_title_and_cover,
)
from session_proxy import StorySessionProxy
from story_identifier import generate_story_id
from story_library import StoryRecord, init_story_library, list_story_records, record_story_export
from telemetry import emit_log_event
from ui.auth import render_auth_gate
from ui.board import render_board_page
from ui.create import CreatePageContext, render_current_step
from ui.home import render_home_screen
from ui.styles import render_app_styles
from utils.auth import (
    auth_display_name,
    auth_email,
    clear_auth_session,
    ensure_active_auth_session,
)
from utils.network import get_client_ip
from utils.time_utils import format_kst

st.set_page_config(page_title="동화책 생성기", page_icon="📖", layout="centered")

JSON_PATH = "storytype.json"
STYLE_JSON_PATH = "illust_styles.json"
STORY_JSON_PATH = "story.json"
ENDING_JSON_PATH = "ending.json"
ILLUST_DIR = "illust"
HOME_BACKGROUND_IMAGE_PATH = Path("assets/illus-home-hero.png")

STORY_STORAGE_MODE_RAW = (os.getenv("STORY_STORAGE_MODE") or "remote").strip().lower()
if STORY_STORAGE_MODE_RAW in {"remote", "gcs"}:
    STORY_STORAGE_MODE = "remote"
else:
    STORY_STORAGE_MODE = "local"

USE_REMOTE_EXPORTS = STORY_STORAGE_MODE == "remote"
STORY_LIBRARY_INIT_ERROR: str | None = None
try:
    init_story_library()
except Exception as exc:  # pragma: no cover - initialization failure surfaced later
    STORY_LIBRARY_INIT_ERROR = str(exc)

init_activity_log()


def _load_json_entries_from_file(path: str | Path, key: str) -> list[dict]:
    """Safely load a list of dict entries from a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    items = payload.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]

@st.cache_data
def load_story_types():
    return _load_json_entries_from_file(JSON_PATH, "story_types")

@st.cache_data
def load_illust_styles():
    return _load_json_entries_from_file(STYLE_JSON_PATH, "illust_styles")


@st.cache_data
def load_story_cards():
    return _load_json_entries_from_file(STORY_JSON_PATH, "cards")


@st.cache_data
def load_ending_cards():
    return _load_json_entries_from_file(ENDING_JSON_PATH, "story_endings")


@st.cache_data(show_spinner=False)
def load_image_as_base64(path: str) -> str | None:
    """지정된 경로의 이미지를 base64 문자열로 반환."""
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return None
    return base64.b64encode(data).decode("utf-8")


story_types = load_story_types()
if not story_types:
    st.error("storytype.json에서 story_types를 찾지 못했습니다.")
    st.stop()

illust_styles = load_illust_styles()
story_cards = load_story_cards()
ending_cards = load_ending_cards()

ensure_state(story_types)
session_proxy = StorySessionProxy(st.session_state)



def logout_user() -> None:
    previous_user = st.session_state.get("auth_user")
    display_name = None
    user_email = None
    if isinstance(previous_user, Mapping):
        display_name = auth_display_name(previous_user)
        user_email = auth_email(previous_user)
    client_ip = get_client_ip()
    clear_auth_session()
    reset_all_state()
    st.session_state["board_user_alias"] = None
    st.session_state["board_content"] = ""
    st.session_state["auth_next_action"] = None
    emit_log_event(
        type="user",
        action="logout",
        result="success",
        params=[client_ip, display_name, None, None, None],
        client_ip=client_ip,
        user_email=user_email,
    )
# ─────────────────────────────────────────────────────────────────────
# 헤더/인증/진행
# ─────────────────────────────────────────────────────────────────────
home_bg = load_image_as_base64(str(HOME_BACKGROUND_IMAGE_PATH))
auth_user = ensure_active_auth_session()
mode = st.session_state.get("mode")
current_step = st.session_state["step"]

if mode in {"create", "board"} and not auth_user:
    st.session_state["auth_next_action"] = mode
    st.session_state["mode"] = "auth"
    st.rerun()

if mode == "auth":
    render_auth_gate(home_bg)
    st.stop()

st.title("📖 동화책 생성기")
header_cols = st.columns([6, 1])

with header_cols[0]:
    if auth_user:
        st.caption(f"👋 **{auth_display_name(auth_user)}**님 반가워요.")
    else:
        st.caption("로그인하면 동화 만들기와 게시판을 이용할 수 있어요.")

with header_cols[1]:
    menu = st.popover("⚙️", width='stretch')
    with menu:
        st.markdown("#### 메뉴")
        if auth_user:
            st.write(f"현재 사용자: **{auth_display_name(auth_user)}**")
            if st.button("로그아웃", width='stretch'):
                logout_user()
                st.rerun()
            st.button("설정 (준비중)", disabled=True, width='stretch')
            st.caption("설정 항목은 준비 중이에요.")
        else:
            if st.button("로그인 / 회원가입", width='stretch'):
                st.session_state["auth_next_action"] = None
                st.session_state["mode"] = "auth"
                st.session_state["auth_form_mode"] = "signin"
                st.session_state["auth_error"] = None
                st.rerun()
            st.button("설정 (로그인 필요)", disabled=True, width='stretch')
            st.caption("로그인하면 더 많은 기능을 사용할 수 있어요.")

progress_placeholder = st.empty()


if mode == "create" and current_step > 0:
    total_phases = len(STORY_PHASES)
    completed_stages = sum(1 for stage in st.session_state.get("stages_data", []) if stage)
    progress_value = 0.0
    if current_step == 1:
        progress_value = 0.15
    elif current_step == 2:
        progress_value = 0.25
    elif current_step == 3:
        progress_value = 0.35
    elif current_step in (4, 5):
        stage_share = completed_stages / total_phases if total_phases else 0.0
        progress_value = 0.35 + stage_share * 0.6
    elif current_step == 6:
        if completed_stages >= total_phases:
            progress_value = 1.0
        else:
            stage_share = completed_stages / total_phases if total_phases else 0.0
            progress_value = 0.35 + stage_share * 0.6
    progress_placeholder.progress(min(progress_value, 1.0))
else:
    progress_placeholder.empty()

if mode == "board":
    render_board_page(home_bg, auth_user=auth_user)
    st.stop()

render_app_styles(home_bg, show_home_hero=current_step == 0)

create_context = CreatePageContext(
    session=session_proxy,
    story_types=story_types,
    illust_styles=illust_styles,
    story_cards=story_cards,
    ending_cards=ending_cards,
    use_remote_exports=USE_REMOTE_EXPORTS,
    auth_user=auth_user,
    home_background=home_bg,
    illust_dir=ILLUST_DIR,
)

if current_step == 0:
    render_home_screen(
        auth_user=auth_user,
        use_remote_exports=USE_REMOTE_EXPORTS,
        story_types=story_types,
    )
elif mode == "create" and current_step in {1, 2, 3, 4, 5, 6}:
    render_current_step(create_context, current_step)
    st.stop()
elif current_step == 5 and mode == "view":
    st.subheader("저장한 동화 보기")
    if STORY_LIBRARY_INIT_ERROR:
        st.warning(f"동화 기록 저장소 초기화 중 문제가 발생했어요: {STORY_LIBRARY_INIT_ERROR}")
    filter_options = ["모두의 동화"]
    if auth_user:
        filter_options.append("내 동화")

    view_filter = st.radio(
        "어떤 동화를 살펴볼까요?",
        filter_options,
        horizontal=True,
        key="story_view_filter",
    )
    if not auth_user:
        st.caption("로그인하면 내가 만든 동화만 모아볼 수 있어요.")

    records: list[StoryRecord] | None = None
    records_error: str | None = None
    try:
        if view_filter == "내 동화" and auth_user:
            records = list_story_records(user_id=str(auth_user.get("uid")), limit=100)
        else:
            records = list_story_records(limit=100)
    except Exception as exc:  # pragma: no cover - defensive catch
        records_error = str(exc)
        records = []

    if records_error:
        st.error(f"동화 기록을 불러오지 못했어요: {records_error}")

    entries: list[dict[str, Any]] = []
    recorded_keys: set[str] = set()

    for record in records:
        key_candidate = (record.gcs_object or record.local_path or record.html_filename or "").lower()
        if key_candidate:
            recorded_keys.add(key_candidate)
        entries.append(
            {
                "token": f"record:{record.id}",
                "title": record.title,
                "author": record.author_name,
                "story_id": record.story_id,
                "created_at": record.created_at_utc,
                "local_path": record.local_path,
                "gcs_object": record.gcs_object,
                "gcs_url": record.gcs_url,
                "html_filename": record.html_filename,
                "origin": "record",
            }
        )

    include_legacy = view_filter != "내 동화"
    if include_legacy:
        legacy_candidates: list[Any] = []
        if USE_REMOTE_EXPORTS:
            if is_gcs_available():
                legacy_candidates = list_gcs_exports()
        else:
            legacy_candidates = list_html_exports()

        for item in legacy_candidates:
            if USE_REMOTE_EXPORTS:
                key = (item.object_name or item.filename).lower()
                if key in recorded_keys:
                    continue
                created_at = item.updated
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                created_at = created_at or datetime.fromtimestamp(0, tz=timezone.utc)
                entries.append(
                    {
                        "token": f"legacy-remote:{item.object_name}",
                        "title": Path(item.filename).stem,
                        "author": None,
                        "created_at": created_at,
                        "local_path": None,
                        "gcs_object": item.object_name,
                        "gcs_url": item.public_url,
                        "html_filename": item.filename,
                        "origin": "legacy-remote",
                    }
                )
            else:
                key = str(item).lower()
                if key in recorded_keys:
                    continue
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                except Exception:
                    mtime = datetime.fromtimestamp(0, tz=timezone.utc)
                entries.append(
                    {
                        "token": f"legacy-local:{item}",
                        "title": item.stem,
                        "author": None,
                        "created_at": mtime,
                        "local_path": str(item),
                        "gcs_object": None,
                        "gcs_url": None,
                        "html_filename": item.name,
                        "origin": "legacy-local",
                    }
                )

    if not entries:
        if view_filter == "내 동화":
            st.info("아직 내가 만든 동화가 없어요. 새 동화를 만들어보세요.")
        else:
            st.info("저장된 동화가 없습니다. 먼저 동화를 생성해주세요.")
    else:
        entries.sort(key=lambda entry: entry.get("created_at", datetime.fromtimestamp(0, tz=timezone.utc)), reverse=True)

        def _format_entry(idx: int) -> str:
            entry = entries[idx]
            created = entry.get("created_at")
            stamp = format_kst(created) if created else "시간 정보 없음"
            author = entry.get("author")
            if author and view_filter != "내 동화":
                return f"{entry['title']} · {author} · {stamp}"
            return f"{entry['title']} · {stamp}"

        tokens = [entry["token"] for entry in entries]
        selected_token = st.session_state.get("selected_export")
        default_index = 0
        if selected_token in tokens:
            default_index = tokens.index(selected_token)

        selected_index = st.selectbox(
            "읽고 싶은 동화를 선택하세요",
            list(range(len(entries))),
            index=default_index,
            format_func=_format_entry,
            key="story_entry_select",
        )

        selected_entry = entries[selected_index]
        st.session_state["selected_export"] = selected_entry["token"]
        st.session_state["view_story_id"] = selected_entry.get("story_id")
        st.session_state["story_export_remote_blob"] = selected_entry.get("gcs_object")
        st.session_state["story_export_remote_url"] = selected_entry.get("gcs_url")

        html_content: str | None = None
        html_error: str | None = None
        local_candidates: list[Path] = []

        local_path = selected_entry.get("local_path")
        if local_path:
            local_candidates.append(Path(local_path))
        html_filename = selected_entry.get("html_filename")
        if html_filename:
            local_candidates.append(HTML_EXPORT_PATH / html_filename)

        for candidate in local_candidates:
            try:
                if candidate.exists():
                    html_content = candidate.read_text("utf-8")
                    st.session_state["story_export_path"] = str(candidate)
                    break
            except Exception as exc:
                html_error = str(exc)

        if html_content is None and selected_entry.get("gcs_object"):
            html_content = download_gcs_export(selected_entry["gcs_object"])
            if html_content is None:
                html_error = "원격 저장소에서 파일을 불러오지 못했어요."

        token = selected_entry["token"]
        story_origin = selected_entry.get("origin")
        story_title_display = selected_entry.get("title")
        story_id_value = selected_entry.get("story_id")

        if html_content is None:
            if html_error:
                st.error(f"동화를 여는 데 실패했습니다: {html_error}")
            else:
                st.error("동화를 여는 데 실패했습니다.")
            if selected_entry.get("gcs_url"):
                st.caption(f"파일 URL: {selected_entry['gcs_url']}")
            elif local_path:
                st.caption(f"파일 경로: {local_path}")
            log_key = f"fail:{token}"
            if st.session_state.get("story_view_logged_token") != log_key:
                emit_log_event(
                    type="story",
                    action="story view",
                    result="fail",
                    params=[
                        story_id_value or token,
                        story_title_display,
                        story_origin,
                        selected_entry.get("gcs_url") or local_path,
                        html_error or "missing content",
                    ],
                )
                st.session_state["story_view_logged_token"] = log_key
        else:
            st.download_button(
                "동화 다운로드",
                data=html_content,
                file_name=selected_entry.get("html_filename") or "story.html",
                mime="text/html",
                width='stretch',
            )
            if selected_entry.get("gcs_url"):
                st.caption(f"파일 URL: {selected_entry['gcs_url']}")
            elif local_path:
                st.caption(f"파일 경로: {local_path}")
            components.html(html_content, height=700, scrolling=True)
            log_key = f"success:{token}"
            if st.session_state.get("story_view_logged_token") != log_key:
                emit_log_event(
                    type="story",
                    action="story view",
                    result="success",
                    params=[
                        story_id_value or token,
                        story_title_display,
                        story_origin,
                        selected_entry.get("gcs_url") or local_path,
                        None,
                    ],
                )
                st.session_state["story_view_logged_token"] = log_key

    c1, c2 = st.columns(2)
    with c1:
        if st.button("← 선택 화면으로", width='stretch'):
            st.session_state["mode"] = None
            st.session_state["step"] = 0
            st.session_state["selected_export"] = None
            st.session_state["story_export_path"] = None
            st.session_state["view_story_id"] = None
            st.session_state["story_view_logged_token"] = None
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", width='stretch'):
            st.session_state["mode"] = "create"
            st.session_state["step"] = 1
            st.session_state["story_view_logged_token"] = None
            st.session_state["view_story_id"] = None
            st.rerun()
