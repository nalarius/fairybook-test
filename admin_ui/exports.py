"""Activity export view."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

import streamlit as st

from admin_tool.activity_service import entry_to_row, gather_activity_entries
from admin_tool.constants import MAX_EXPORT_ROWS
from admin_tool.exporter import export_rows_to_google_sheet, rows_to_csv_bytes

from . import common


EVENT_TYPE_OPTIONS = ("story", "user", "board", "moderation", "admin")
RESULT_OPTIONS = ("success", "fail")

def render_exports(
    admin_user: Mapping[str, Any],
    *,
    log_admin_event: Callable[..., None],
    admin_email_lookup: Callable[[Mapping[str, Any]], str | None],
) -> None:
    st.title("⬇️ 로그 내보내기")
    st.caption(
        "필터 조건으로 활동 로그를 조회하고 CSV 또는 Google Sheets로 내보낼 수 있습니다. "
        "Google Sheets 내보내기를 사용하려면 서비스 계정에 시트 편집 권한이 있어야 해요."
    )

    filters_state = st.session_state.setdefault(
        "admin_export_filters",
        {
            "start_date": date.today() - timedelta(days=7),
            "end_date": date.today(),
            "types": list(EVENT_TYPE_OPTIONS),
            "results": list(RESULT_OPTIONS),
            "actions": [],
        },
    )

    with st.form("export_filters"):
        start_end = st.date_input(
            "조회 기간",
            value=(filters_state["start_date"], filters_state["end_date"]),
            max_value=date.today(),
        )
        selected_types = st.multiselect(
            "이벤트 유형",
            options=EVENT_TYPE_OPTIONS,
            default=filters_state.get("types", EVENT_TYPE_OPTIONS),
        )
        selected_results = st.multiselect(
            "결과",
            options=RESULT_OPTIONS,
            default=filters_state.get("results", RESULT_OPTIONS),
        )
        action_tokens = st.text_input(
            "액션 필터 (쉼표로 구분)",
            value=", ".join(filters_state.get("actions", [])),
        )
        submitted = st.form_submit_button("필터 적용", type="primary")

    if isinstance(start_end, tuple) and len(start_end) == 2:
        filters_state["start_date"], filters_state["end_date"] = start_end

    if submitted:
        filters_state["types"] = list(selected_types)
        filters_state["results"] = list(selected_results)
        filters_state["actions"] = list(common.parse_action_tokens(action_tokens))

    filters = common.filters_from_state(filters_state)
    entries = gather_activity_entries(filters, max_records=MAX_EXPORT_ROWS)
    rows = [entry_to_row(entry) for entry in entries]

    st.write(f"가져온 로그 수: {len(rows):,} / 최대 {MAX_EXPORT_ROWS:,}")

    if not rows:
        st.info("현재 조건으로 내보낼 로그가 없습니다.")
        return

    csv_data = rows_to_csv_bytes(rows)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"activity_logs_{timestamp}.csv"

    st.download_button(
        "CSV 다운로드",
        data=csv_data,
        file_name=csv_filename,
        mime="text/csv",
        type="primary",
    )

    spreadsheet_id = st.text_input(
        "Google Sheets 스프레드시트 ID",
        value="",
        help="https://docs.google.com/spreadsheets/d/<ID>/ 형식의 ID를 입력하세요.",
        key="export_sheet_id",
    )

    if st.button("Google Sheets로 내보내기", disabled=not spreadsheet_id):
        identifier = admin_email_lookup(admin_user)
        try:
            sheet_url = export_rows_to_google_sheet(
                rows,
                spreadsheet_id=spreadsheet_id,
                worksheet_title=f"activity_logs_{timestamp}",
            )
        except Exception as exc:  # pragma: no cover
            st.error(f"Sheets 내보내기에 실패했어요: {exc}")
            log_admin_event(
                "export sheets",
                "fail",
                admin_identifier=identifier,
                params=[spreadsheet_id, str(exc), None, None, None],
            )
        else:
            st.success("내보내기가 완료되었습니다.")
            st.markdown(f"[열기]({sheet_url})")
            log_admin_event(
                "export sheets",
                "success",
                admin_identifier=identifier,
                params=[spreadsheet_id, sheet_url, None, None, None],
            )


__all__ = ["render_exports"]
