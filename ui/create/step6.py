"""Step 6 view: aggregate story, export, and present downloads."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from app_constants import STORY_PHASES
from gcs_storage import download_gcs_export, is_gcs_available, list_gcs_exports
from services.story_service import StagePayload, StoryBundle, export_story_to_html, list_html_exports
from story_library import record_story_export
from telemetry import emit_log_event
from utils.auth import auth_display_name, auth_email
from utils.time_utils import format_kst

from session_state import reset_all_state, reset_story_session

from .context import CreatePageContext


def render_step(context: CreatePageContext) -> None:
    session = context.session
    auth_user = context.auth_user
    use_remote_exports = context.use_remote_exports

    st.subheader("6단계. 이야기를 모아봤어요")

    title_val = (session.get("story_title") or "동화").strip()
    age_val = session.get("age") or "6-8"
    topic_val = session.get("topic") or ""
    topic_display = topic_val if topic_val else "(빈칸)"
    rand8 = session.get("rand8") or []
    selected_type_idx = session.get("selected_type_idx", 0)
    story_type_name = (
        rand8[selected_type_idx].get("name", "이야기 유형")
        if 0 <= selected_type_idx < len(rand8)
        else "이야기 유형"
    )

    stages_data = session.get("stages_data") or []
    completed_stages = [entry for entry in stages_data if entry]

    if len(completed_stages) < len(STORY_PHASES):
        st.info("아직 모든 단계가 완성되지 않았어요. 남은 단계를 이어가면 이야기가 더 풍성해집니다.")
        try:
            next_stage_idx = next(idx for idx, entry in enumerate(stages_data) if not entry)
        except StopIteration:
            next_stage_idx = len(STORY_PHASES) - 1

        if st.button("남은 단계 이어가기 →", width='stretch'):
            session["current_stage_idx"] = next_stage_idx
            reset_story_session(
                keep_title=True,
                keep_cards=False,
                keep_synopsis=True,
                keep_protagonist=True,
                keep_character=True,
                keep_style=True,
            )
            session["step"] = 4
            st.rerun()
        st.stop()

    cover_image = session.get("cover_image")
    cover_error = session.get("cover_image_error")
    cover_style = session.get("story_style_choice") or session.get("cover_image_style")

    export_ready_stages: list[StagePayload] = []
    display_sections: list[dict[str, Any]] = []
    text_lines: list[str] = [title_val, ""]
    signature_payload = {
        "title": title_val,
        "age": age_val,
        "topic": topic_val or "",
        "story_type": story_type_name,
        "stages": [],
        "cover_hash": None,
    }

    for idx, stage_name in enumerate(STORY_PHASES):
        entry = stages_data[idx] if idx < len(stages_data) else None
        if not entry:
            display_sections.append({"missing": stage_name})
            continue
        card_info = entry.get("card", {})
        story_info = entry.get("story", {})
        paragraphs = story_info.get("paragraphs", [])
        text_lines.extend(paragraphs)
        text_lines.append("")

        image_bytes = entry.get("image_bytes")
        image_hash = hashlib.sha256(image_bytes).hexdigest() if image_bytes else None

        export_ready_stages.append(
            StagePayload(
                stage_name=stage_name,
                card_name=card_info.get("name"),
                card_prompt=card_info.get("prompt"),
                paragraphs=paragraphs,
                image_bytes=image_bytes,
                image_mime=entry.get("image_mime") or "image/png",
                image_style_name=(entry.get("image_style") or {}).get("name"),
            )
        )
        signature_payload["stages"].append(
            {
                "stage_name": stage_name,
                "card_name": card_info.get("name"),
                "paragraphs": paragraphs,
                "image_hash": image_hash,
            }
        )
        display_sections.append(
            {
                "image_bytes": image_bytes,
                "image_error": entry.get("image_error"),
                "paragraphs": paragraphs,
            }
        )

    full_text = "\n".join(line for line in text_lines if line is not None)

    cover_payload = None
    cover_hash = None
    if cover_image:
        cover_mime = session.get("cover_image_mime", "image/png")
        cover_payload = {
            "image_bytes": cover_image,
            "image_mime": cover_mime,
            "style_name": (cover_style or {}).get("name"),
        }
        cover_hash = hashlib.sha256(cover_image).hexdigest()

    signature_payload["cover_hash"] = cover_hash
    signature_raw = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
    signature = hashlib.sha256(signature_raw.encode("utf-8")).hexdigest()

    auto_saved = False
    if session.get("story_export_signature") != signature:
        try:
            bundle = StoryBundle(
                title=title_val,
                stages=export_ready_stages,
                synopsis=session.get("synopsis_result"),
                protagonist=session.get("protagonist_result"),
                cover=cover_payload,
                story_type_name=story_type_name,
                age=age_val,
                topic=topic_val,
            )
            export_result = export_story_to_html(
                bundle=bundle,
                author=auth_display_name(auth_user) if auth_user else None,
                use_remote_exports=use_remote_exports,
            )
            session["story_export_path"] = export_result.local_path
            session["story_export_signature"] = signature
            if use_remote_exports:
                session["story_export_remote_url"] = export_result.gcs_url
                session["story_export_remote_blob"] = export_result.gcs_object
                if export_result.gcs_object:
                    session["selected_export"] = f"gcs:{export_result.gcs_object}"
                else:
                    session["selected_export"] = export_result.local_path
            else:
                session["story_export_remote_url"] = None
                session["story_export_remote_blob"] = None
                session["selected_export"] = export_result.local_path
            auto_saved = True
            user_email = auth_email(auth_user)
            emit_log_event(
                type="story",
                action="story save",
                result="success",
                params=[
                    session.get("story_id"),
                    title_val,
                    export_result.gcs_object or export_result.local_path,
                    export_result.gcs_url,
                    "auto-save",
                ],
                user_email=user_email,
            )
            if auth_user:
                try:
                    record_story_export(
                        user_id=str(auth_user.get("uid", "")),
                        title=title_val,
                        local_path=export_result.local_path,
                        gcs_object=export_result.gcs_object,
                        gcs_url=export_result.gcs_url,
                        story_id=session.get("story_id"),
                        author_name=auth_display_name(auth_user),
                    )
                except Exception as exc:  # pragma: no cover
                    emit_log_event(
                        type="story",
                        action="story save",
                        result="fail",
                        params=[
                            session.get("story_id"),
                            title_val,
                            export_result.gcs_object or export_result.local_path,
                            export_result.gcs_url,
                            f"library error: {exc}",
                        ],
                    )
        except Exception as exc:  # pragma: no cover
            st.warning(f"자동 저장에 실패했습니다: {exc}")
            emit_log_event(
                type="story",
                action="story save",
                result="fail",
                params=[
                    session.get("story_id"),
                    title_val,
                    None,
                    None,
                    str(exc),
                ],
            )

    st.markdown("#### 완성된 동화 정보")
    st.caption(f"나이대: **{age_val}** · 주제: **{topic_display}** · 이야기 유형: **{story_type_name}**")
    st.caption(f"단계 수: {len(STORY_PHASES)} · 본문 길이: {len(full_text.split())} 단어")

    export_path_current = session.get("story_export_path")
    export_remote_url = session.get("story_export_remote_url")
    export_remote_blob = session.get("story_export_remote_blob")

    if auto_saved:
        st.success("새로운 이야기를 자동으로 저장했어요.")
    elif export_path_current or export_remote_url:
        st.info("최근 저장한 동화입니다. 필요하면 다시 내려받으세요.")

    if use_remote_exports:
        selected_export_token = session.get("selected_export")
        options: list[tuple[str, str]] = []
        if export_remote_blob and export_remote_url:
            options.append((f"gcs:{export_remote_blob}", f"신규 업로드 · {Path(export_remote_blob).name}"))

        if is_gcs_available():
            for item in list_gcs_exports():
                token = f"gcs:{item.object_name}"
                label = f"{Path(item.filename).stem} ({format_kst(item.updated)})"
                options.append((token, label))

        if options:
            selected_export_token = st.selectbox(
                "다운로드할 동화를 선택하세요",
                options,
                format_func=lambda item: item[1],
                index=next((idx for idx, opt in enumerate(options) if opt[0] == selected_export_token), 0),
                key="story_export_selector",
            )[0]
            session["selected_export"] = selected_export_token

            if selected_export_token and selected_export_token.startswith("gcs:"):
                blob_name = selected_export_token.split(":", 1)[1]
                if st.button("📥 GCS에서 다운로드", key="download_selected_gcs", use_container_width=True):
                    download_gcs_export(blob_name)
        else:
            st.info("아직 업로드한 동화가 없어요.")
    else:
        if export_path_current:
            st.caption(f"로컬 파일: {export_path_current}")
        else:
            st.info("내려받을 수 있는 HTML 파일이 아직 없습니다.")

    st.markdown(f"### {title_val}")
    if cover_image:
        st.image(cover_image, width='stretch')
    elif cover_error:
        st.caption("표지 일러스트를 준비하지 못했어요.")

    last_export = session.get("story_export_path")
    last_remote = session.get("story_export_remote_url")

    for idx, section in enumerate(display_sections):
        if section.get("missing"):
            st.warning("이야기 단계가 비어 있습니다. 다시 생성해 주세요.")
            continue

        image_bytes = section.get("image_bytes")
        image_error = section.get("image_error")
        paragraphs = section.get("paragraphs") or []

        if image_bytes:
            st.image(image_bytes, width='stretch')
        elif image_error:
            st.caption("삽화를 준비하지 못했어요.")

        for paragraph in paragraphs:
            st.write(paragraph)

        if idx < len(display_sections) - 1:
            st.markdown("---")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← 첫 화면으로", width='stretch'):
            reset_all_state()
            st.rerun()
    with c2:
        if st.button("✏️ 새 동화 만들기", width='stretch'):
            reset_all_state()
            session["mode"] = "create"
            session["step"] = 1
            st.rerun()
    with c3:
        if st.button("📂 저장한 동화 보기", width='stretch'):
            session["mode"] = "view"
            session["step"] = 5
            st.rerun()

