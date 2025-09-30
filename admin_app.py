"""Standalone Streamlit admin console for monitoring and moderation."""
from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import streamlit as st

try:  # Optional analytics helpers
    import altair as alt  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    alt = None

try:  # Optional DataFrame support
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pd = None

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
if ENV_PATH.is_file():
    load_dotenv(ENV_PATH, override=False)

from activity_log import init_activity_log, is_activity_logging_enabled, log_event
from admin_tool.activity_service import (
    ActivityFilters,
    entry_to_row,
    fetch_activity_page,
    gather_activity_entries,
    summarize_entries,
)
from admin_tool.auth import (
    admin_display_name,
    admin_email,
    admin_error_message,
    clear_admin_session,
    ensure_active_admin_session,
    store_admin_session,
)
from admin_tool.constants import (
    DEFAULT_DASHBOARD_RANGE_DAYS,
    DEFAULT_PAGE_SIZE,
    MAX_EXPORT_ROWS,
    MODERATION_REASON_CODES,
    MODERATION_TARGET_TYPES,
    SANCTION_DURATION_PRESETS,
)
from admin_tool.exporter import export_rows_to_google_sheet, rows_to_csv_bytes
from admin_tool.user_service import (
    AdminUser,
    apply_user_sanction,
    generate_password_reset,
    list_users,
    set_user_disabled,
    set_user_role,
)
from firebase_auth import AuthSession, FirebaseAuthError, sign_in, verify_id_token
from utils.network import get_client_ip


def _trigger_rerun() -> None:
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if callable(rerun_fn):
        rerun_fn()
    else:  # pragma: no cover - fallback for extremely old Streamlit
        st.session_state["_admin_force_rerun"] = st.session_state.get("_admin_force_rerun", 0) + 1


st.set_page_config(page_title="운영자 콘솔", page_icon="🛡️", layout="wide")
init_activity_log()

NAV_KEY = "admin_nav_selection"
DASHBOARD_STATE_KEY = "admin_dashboard_filters"
ACTIVITY_FILTER_STATE_KEY = "admin_activity_filters"
ACTIVITY_CURSOR_KEY = "admin_activity_cursor"
USER_SEARCH_STATE_KEY = "admin_user_directory_state"

EVENT_TYPE_OPTIONS = ("story", "user", "board", "moderation", "admin")
RESULT_OPTIONS = ("success", "fail")


def _log_admin_event(
    action: str,
    result: str,
    *,
    admin_identifier: str | None,
    params: Sequence[str | None] | None = None,
    metadata: Mapping | None = None,
) -> None:
    try:
        log_event(
            type="admin",
            action=action,
            result=result,
            user_id=admin_identifier,
            params=params,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover - logging should not block UI
        st.warning(f"로그 기록에 실패했습니다: {exc}")


def _log_moderation_event(
    action: str,
    result: str,
    *,
    admin_identifier: str | None,
    params: Sequence[str | None],
    metadata: Mapping | None = None,
) -> None:
    try:
        log_event(
            type="moderation",
            action=action,
            result=result,
            user_id=admin_identifier,
            params=params,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover
        st.warning(f"모더레이션 로그 기록 실패: {exc}")


def _render_login() -> None:
    st.title("🛡️ 동화책 생성기 운영자 콘솔")
    st.subheader("관리자 인증")

    if error := admin_error_message():
        st.error(error)

    st.caption("관리자 전용 페이지입니다. 전용 계정으로 로그인해 주세요.")

    with st.form("admin_login_form", clear_on_submit=False):
        email = st.text_input("이메일", placeholder="admin@example.com", max_chars=120, key="admin_login_email")
        password = st.text_input("비밀번호", type="password", key="admin_login_password")
        submitted = st.form_submit_button("로그인", type="primary")

    if not submitted:
        return

    normalized_email = email.strip()
    if not normalized_email or not password:
        st.error("이메일과 비밀번호를 모두 입력해 주세요.")
        return

    client_ip = get_client_ip()

    try:
        session = sign_in(normalized_email, password)
    except FirebaseAuthError as exc:
        st.error(f"Firebase 인증에 실패했어요: {exc} (코드 확인 필요)")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "signin", client_ip, str(exc), None],
        )
        return
    except Exception as exc:  # pragma: no cover - defensive guard
        st.error(f"로그인을 처리하지 못했어요: {exc}")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "signin", client_ip, str(exc), None],
        )
        return

    try:
        claims = verify_id_token(session.id_token)
    except Exception as exc:  # pragma: no cover - verification failure
        message = str(exc)
        if "Token used too early" in message:
            time.sleep(2)
            try:
                claims = verify_id_token(session.id_token)
            except Exception as retry_exc:  # pragma: no cover - second failure
                st.error(f"ID 토큰을 검증하는 중 오류가 발생했습니다: {retry_exc}")
                _log_admin_event(
                    "login",
                    "fail",
                    admin_identifier=normalized_email,
                    params=[normalized_email, "verify", client_ip, str(retry_exc), None],
                )
                return
        else:
            st.error(f"ID 토큰을 검증하는 중 오류가 발생했습니다: {exc}")
            _log_admin_event(
                "login",
                "fail",
                admin_identifier=normalized_email,
                params=[normalized_email, "verify", client_ip, str(exc), None],
            )
            return

    if claims.get("role") != "admin":
        st.error("관리자 권한이 없는 계정입니다. 관리자에게 문의해 주세요.")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "role-check", client_ip, "missing-admin-role", None],
        )
        return

    store_admin_session(session)
    st.session_state["admin_claims"] = claims
    _log_admin_event(
        "login",
        "success",
        admin_identifier=normalized_email,
        params=[normalized_email, "signin", client_ip, None, None],
    )
    st.success("로그인 되었습니다. 콘솔을 준비하고 있어요…")
    st.session_state["admin_nav_selection"] = "대시보드"
    _trigger_rerun()


def _sidebar(admin_user: Mapping[str, Any]) -> str:
    with st.sidebar:
        st.header("관리자 메뉴")
        st.caption("동화책 생성기 운영 현황을 모니터링하세요.")

        name = admin_display_name(admin_user)
        email = admin_email(admin_user) or "—"
        if name and name.strip() and name != email:
            st.markdown(f"**{name}**\n\n{email}")
        else:
            st.markdown(f"**{email}**")

        activity_enabled = is_activity_logging_enabled()
        if not activity_enabled:
            st.warning("활동 로그가 비활성화되어 있어 일부 통계가 최신이 아닐 수 있어요.")

        selection = st.radio(
            "섹션",
            options=(
                "대시보드",
                "사용자 디렉터리",
                "활동 탐색기",
                "내보내기",
            ),
            key=NAV_KEY,
        )

        if st.button("로그아웃", type="secondary"):
            identifier = admin_email(admin_user)
            _log_admin_event(
                "logout",
                "success",
                admin_identifier=identifier,
                params=[identifier, None, None, None, None],
            )
            clear_admin_session()
            _trigger_rerun()

        st.divider()
        st.caption("문제가 있으면 Slack #operations 로 알려주세요.")

    return selection


def _apply_date_filters(state: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_date: date = state.get("start_date") or (date.today() - timedelta(days=DEFAULT_DASHBOARD_RANGE_DAYS))
    end_date: date = state.get("end_date") or date.today()

    if start_date > end_date:
        start_date, end_date = end_date, start_date
        state["start_date"] = start_date
        state["end_date"] = end_date

    start_dt = datetime.combine(start_date, datetime_time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime_time.max, tzinfo=timezone.utc)
    return start_dt, end_dt


def _parse_action_tokens(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return tuple()
    tokens = {token.strip() for token in raw.split(",") if token.strip()}
    return tuple(sorted(tokens))


def _filters_from_state(state: dict[str, Any]) -> ActivityFilters:
    start_ts, end_ts = _apply_date_filters(state)
    types = tuple(state.get("types") or ())
    actions = tuple(state.get("actions") or ())
    results = tuple(state.get("results") or ())
    return ActivityFilters(
        types=types,
        actions=actions,
        results=results,
        start_ts=start_ts,
        end_ts=end_ts,
    )


def _render_summary_cards(summary) -> None:
    cols = st.columns(3)
    cols[0].metric("총 이벤트", f"{summary.total_events:,}")
    cols[1].metric("실패", f"{summary.failures:,}", delta=f"{summary.failure_rate*100:.1f}%")
    cols[2].metric("고유 사용자", f"{summary.distinct_users:,}")


def _render_daily_chart(summary) -> None:
    if not summary.daily_counts or not pd or not alt:  # pragma: no cover - optional charting
        return
    df = pd.DataFrame(
        {"date": list(summary.daily_counts.keys()), "count": list(summary.daily_counts.values())}
    ).sort_values("date")
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title="날짜"),
            y=alt.Y("count:Q", title="이벤트 수"),
            tooltip=["date:T", "count:Q"],
        )
    )
    st.altair_chart(chart, use_container_width=True)


def _render_top_actions(summary) -> None:
    if not summary.by_action:
        return
    st.markdown("#### 최다 발생 액션")
    rows = sorted(summary.by_action.items(), key=lambda item: item[1], reverse=True)[:10]
    st.table({"Action": [row[0] for row in rows], "Count": [row[1] for row in rows]})


def _render_dashboard(admin_user: Mapping[str, Any]) -> None:
    st.title("📊 사용량 대시보드")
    state = st.session_state.setdefault(
        DASHBOARD_STATE_KEY,
        {
            "start_date": date.today() - timedelta(days=DEFAULT_DASHBOARD_RANGE_DAYS),
            "end_date": date.today(),
            "types": list(EVENT_TYPE_OPTIONS),
            "results": list(RESULT_OPTIONS),
            "actions": [],
        },
    )

    with st.form("dashboard_filters"):
        start_end = st.date_input(
            "조회 기간",
            value=(state["start_date"], state["end_date"]),
            max_value=date.today(),
        )
        selected_types = st.multiselect(
            "이벤트 유형",
            options=EVENT_TYPE_OPTIONS,
            default=state.get("types", EVENT_TYPE_OPTIONS),
        )
        selected_results = st.multiselect(
            "결과",
            options=RESULT_OPTIONS,
            default=state.get("results", RESULT_OPTIONS),
        )
        action_tokens = st.text_input(
            "특정 액션 필터 (쉼표로 구분)",
            value=", ".join(state.get("actions", [])),
        )
        submitted = st.form_submit_button("필터 적용", type="primary")

    if isinstance(start_end, tuple) and len(start_end) == 2:
        state["start_date"], state["end_date"] = start_end

    if submitted:
        state["types"] = list(selected_types)
        state["results"] = list(selected_results)
        state["actions"] = list(_parse_action_tokens(action_tokens))

    filters = _filters_from_state(state)
    entries = gather_activity_entries(filters, max_records=DEFAULT_PAGE_SIZE * 5)

    if not entries:
        st.info("선택한 조건에 해당하는 로그가 없습니다.")
        return

    summary = summarize_entries(entries)
    _render_summary_cards(summary)
    _render_daily_chart(summary)
    _render_top_actions(summary)


@st.cache_data(show_spinner=False)
def _serialize_activity_page(entries: Sequence[Any]) -> list[dict[str, Any]]:
    return [entry_to_row(entry) for entry in entries]


def _render_activity_table(entries: Sequence[Any]) -> None:
    rows = _serialize_activity_page(entries)
    if not rows:
        st.info("표시할 로그가 없습니다.")
        return
    if pd:
        st.dataframe(pd.DataFrame(rows))
    else:  # pragma: no cover - fallback rendering
        st.json(rows)


def _render_activity_explorer(admin_user: Mapping[str, Any]) -> None:
    st.title("🔍 활동 탐색기")
    state = st.session_state.setdefault(
        ACTIVITY_FILTER_STATE_KEY,
        {
            "start_date": date.today() - timedelta(days=7),
            "end_date": date.today(),
            "types": list(EVENT_TYPE_OPTIONS),
            "results": list(RESULT_OPTIONS),
            "actions": [],
        },
    )

    with st.form("activity_filters"):
        start_end = st.date_input(
            "조회 기간",
            value=(state["start_date"], state["end_date"]),
            max_value=date.today(),
        )
        selected_types = st.multiselect(
            "이벤트 유형",
            options=EVENT_TYPE_OPTIONS,
            default=state.get("types", EVENT_TYPE_OPTIONS),
        )
        selected_results = st.multiselect(
            "결과",
            options=RESULT_OPTIONS,
            default=state.get("results", RESULT_OPTIONS),
        )
        action_tokens = st.text_input(
            "액션 필터 (쉼표로 구분)",
            value=", ".join(state.get("actions", [])),
        )
        page_size = st.slider("한 번에 불러올 로그 수", 20, 200, DEFAULT_PAGE_SIZE)
        submitted = st.form_submit_button("필터 적용", type="primary")

    if isinstance(start_end, tuple) and len(start_end) == 2:
        state["start_date"], state["end_date"] = start_end

    if submitted:
        state["types"] = list(selected_types)
        state["results"] = list(selected_results)
        state["actions"] = list(_parse_action_tokens(action_tokens))
        st.session_state[ACTIVITY_CURSOR_KEY] = None

    filters = _filters_from_state(state)
    cursor = st.session_state.get(ACTIVITY_CURSOR_KEY)
    page = fetch_activity_page(filters, cursor=cursor, limit=page_size)

    _render_activity_table(page.entries)

    buttons = st.columns(3)
    if buttons[0].button("처음부터", disabled=cursor is None):
        st.session_state[ACTIVITY_CURSOR_KEY] = None
        _trigger_rerun()
    if page.has_more and page.next_cursor:
        if buttons[2].button("더 보기"):
            st.session_state[ACTIVITY_CURSOR_KEY] = page.next_cursor
            _trigger_rerun()


def _render_user_card(user: AdminUser, *, administrator: Mapping[str, Any]) -> None:
    with st.expander(f"{user.email or user.uid}"):
        cols = st.columns(4)
        cols[0].write(f"UID: {user.uid}")
        cols[1].write(f"상태: {'비활성화' if user.disabled else '활성'}")
        cols[2].write(f"역할: {user.role or '미지정'}")
        cols[3].write(f"최근 로그인: {user.last_sign_in.isoformat() if user.last_sign_in else '—'}")

        action_cols = st.columns(3)
        toggle_label = "재활성화" if user.disabled else "사용 중지"
        if action_cols[0].button(toggle_label, key=f"toggle-{user.uid}"):
            try:
                updated = set_user_disabled(user.uid, not user.disabled)
            except FirebaseAuthError as exc:  # pragma: no cover - network failure
                st.error(f"상태를 변경하지 못했어요: {exc}")
            else:
                identifier = admin_email(administrator)
                _log_admin_event(
                    "user disable" if updated.disabled else "user enable",
                    "success",
                    admin_identifier=identifier,
                    params=[user.uid, toggle_label, None, None, None],
                )
                st.success("변경되었습니다.")
                _trigger_rerun()

        if user.email and action_cols[1].button("재설정 링크", key=f"reset-{user.uid}"):
            try:
                link = generate_password_reset(user.email)
            except Exception as exc:  # pragma: no cover
                st.error(f"재설정 링크를 생성하지 못했어요: {exc}")
            else:
                identifier = admin_email(administrator)
                _log_admin_event(
                    "password reset",
                    "success",
                    admin_identifier=identifier,
                    params=[user.uid, user.email, link, None, None],
                )
                st.info(f"재설정 링크가 생성되었습니다: {link}")

        with st.form(f"role-form-{user.uid}"):
            selected_role = st.selectbox(
                "역할",
                options=("", "support", "admin"),
                index=(0 if not user.role else (2 if user.role == "admin" else 1)),
                help="빈 값으로 선택하면 역할을 제거합니다.",
            )
            if st.form_submit_button("역할 업데이트"):
                try:
                    updated = set_user_role(user.uid, selected_role or None)
                except Exception as exc:  # pragma: no cover
                    st.error(f"역할을 변경하지 못했어요: {exc}")
                else:
                    identifier = admin_email(administrator)
                    _log_admin_event(
                        "role promote" if updated.role else "role clear",
                        "success",
                        admin_identifier=identifier,
                        params=[user.uid, selected_role or "none", None, None, None],
                    )
                    st.success("역할이 변경되었습니다.")
                    _trigger_rerun()

        st.markdown("#### 제재 적용")
        with st.form(f"sanction-form-{user.uid}"):
            sanction_type = st.selectbox("제재 유형", options=("ban", "mute", "unban"))
            duration = st.selectbox("지속 시간", options=SANCTION_DURATION_PRESETS)
            reason = st.selectbox("사유", options=MODERATION_REASON_CODES)
            target_context = st.text_input("관련 ID (게시글/스토리 등)")
            note = st.text_area("메모 (최대 280자)", max_chars=280)
            submitted = st.form_submit_button("제재 적용")

        if submitted:
            identifier = admin_email(administrator)
            try:
                updated, sanction_payload = apply_user_sanction(
                    user.uid,
                    sanction_type=sanction_type,
                    duration=duration,
                    reason=reason,
                    note=note,
                    context_id=target_context or None,
                    applied_by=identifier,
                )
            except Exception as exc:  # pragma: no cover
                st.error(f"제재 적용에 실패했어요: {exc}")
                _log_moderation_event(
                    "user sanction",
                    "fail",
                    admin_identifier=identifier,
                    params=[user.uid, sanction_type, duration, note, target_context],
                    metadata={"error": str(exc)},
                )
            else:
                st.success("제재 정보가 업데이트되었습니다.")
                _log_moderation_event(
                    "user sanction" if sanction_type != "unban" else "user sanction clear",
                    "success",
                    admin_identifier=identifier,
                    params=[
                        user.uid,
                        sanction_type,
                        duration,
                        note,
                        target_context,
                    ],
                    metadata=sanction_payload,
                )
                _trigger_rerun()

        if user.sanction:
            st.info(f"현재 제재 상태: {user.sanction}")


def _render_user_directory(admin_user: Mapping[str, Any]) -> None:
    st.title("👥 사용자 디렉터리")
    state = st.session_state.setdefault(
        USER_SEARCH_STATE_KEY,
        {
            "search": "",
            "page_size": DEFAULT_PAGE_SIZE,
            "page_token": None,
        },
    )

    with st.form("user_search_form"):
        search = st.text_input("이메일 또는 UID", value=state.get("search", ""))
        page_size = st.slider("페이지 크기", 20, 200, state.get("page_size", DEFAULT_PAGE_SIZE))
        submitted = st.form_submit_button("조회", type="primary")

    if submitted:
        state["search"] = search
        state["page_size"] = page_size
        state["page_token"] = None

    try:
        users, next_token = list_users(
            page_size=state.get("page_size", DEFAULT_PAGE_SIZE),
            page_token=state.get("page_token"),
            search=state.get("search") or None,
        )
    except Exception as exc:  # pragma: no cover - firebase admin failure
        st.error(f"사용자 목록을 불러오지 못했어요: {exc}")
        return

    if not users:
        st.info("조건에 맞는 사용자를 찾지 못했습니다.")
        return

    for user in users:
        _render_user_card(user, administrator=admin_user)

    nav_cols = st.columns(2)
    if nav_cols[0].button("처음으로", disabled=state.get("page_token") is None):
        state["page_token"] = None
        _trigger_rerun()

    if next_token and nav_cols[1].button("다음 페이지"):
        state["page_token"] = next_token
        _trigger_rerun()


def _serialize_for_export(entries: Sequence[Any]) -> list[dict[str, Any]]:
    return [entry_to_row(entry) for entry in entries]


def _render_exports(admin_user: Mapping[str, Any]) -> None:
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
        filters_state["actions"] = list(_parse_action_tokens(action_tokens))

    filters = _filters_from_state(filters_state)
    entries = gather_activity_entries(filters, max_records=MAX_EXPORT_ROWS)
    rows = _serialize_for_export(entries)

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
        identifier = admin_email(admin_user)
        try:
            sheet_url = export_rows_to_google_sheet(
                rows,
                spreadsheet_id=spreadsheet_id,
                worksheet_title=f"activity_logs_{timestamp}",
            )
        except Exception as exc:  # pragma: no cover - external dependency
            st.error(f"Sheets 내보내기에 실패했어요: {exc}")
            _log_admin_event(
                "export sheets",
                "fail",
                admin_identifier=identifier,
                params=[spreadsheet_id, str(exc), None, None, None],
            )
        else:
            st.success("내보내기가 완료되었습니다.")
            st.markdown(f"[열기]({sheet_url})")
            _log_admin_event(
                "export sheets",
                "success",
                admin_identifier=identifier,
                params=[spreadsheet_id, sheet_url, None, None, None],
            )


def _resolve_admin_session() -> tuple[dict[str, Any] | None, Mapping | None]:
    session_state = ensure_active_admin_session()
    if not session_state:
        return None, None

    claims = st.session_state.get("admin_claims")
    if not isinstance(claims, Mapping):
        try:
            claims = verify_id_token(str(session_state.get("id_token")))
        except Exception:  # pragma: no cover
            claims = {}
        st.session_state["admin_claims"] = claims
    return session_state, claims


def main() -> None:
    admin_session, _claims = _resolve_admin_session()
    if not admin_session:
        _render_login()
        return

    section = _sidebar(admin_session)

    if section == "대시보드":
        _render_dashboard(admin_session)
    elif section == "사용자 디렉터리":
        _render_user_directory(admin_session)
    elif section == "활동 탐색기":
        _render_activity_explorer(admin_session)
    else:
        _render_exports(admin_session)


if __name__ == "__main__":
    main()
