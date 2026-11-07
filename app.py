"""LedgerMatch — a local transaction reconciliation workspace."""

from __future__ import annotations

import dataclasses
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from recon.db import (
    format_utc_timestamp,
    get_run,
    initialize_database,
    list_runs,
    save_reconciliation,
)
from recon.engine import (
    CSVValidationError,
    RESULT_DUP_BOTH,
    RESULT_DUP_CORE,
    RESULT_DUP_PROVIDER,
    RESULT_MATCHED,
    RESULT_MISMATCHED,
    RESULT_MISSING_CORE,
    RESULT_MISSING_PROVIDER,
    ReconciliationResult,
    reconcile_files,
)
from recon.reports import build_csv_report, build_excel_report

APP_ROOT = Path(__file__).resolve().parent
SAMPLE_CORE = APP_ROOT / "sample_data" / "core_banking_transactions.csv"
SAMPLE_PROVIDER = APP_ROOT / "sample_data" / "payment_provider_transactions.csv"

UPLOAD_MODE = "Upload CSV files"
SAMPLE_MODE = "Built-in sample data"

MISSING_RESULTS = {RESULT_MISSING_CORE, RESULT_MISSING_PROVIDER}
DUPLICATE_RESULTS = {RESULT_DUP_BOTH, RESULT_DUP_CORE, RESULT_DUP_PROVIDER}
DISCREPANCY_TYPES = [
    RESULT_MISMATCHED,
    RESULT_MISSING_PROVIDER,
    RESULT_MISSING_CORE,
    RESULT_DUP_BOTH,
    RESULT_DUP_CORE,
    RESULT_DUP_PROVIDER,
]

RESULT_VIEW_COLUMNS = {
    "result": "Result",
    "reference": "Reference",
    "core_transaction_id": "Core transaction ID",
    "provider_transaction_id": "Provider transaction ID",
    "core_amount": "Core amount",
    "provider_amount": "Provider amount",
    "amount_difference": "Difference",
    "core_date": "Core date",
    "provider_date": "Provider date",
    "core_status": "Core status",
    "provider_status": "Provider status",
    "mismatch_fields": "Mismatch",
    "core_count": "Core recs",
    "provider_count": "Provider recs",
    "note": "Review note",
}

AMOUNT_LABELS = {"Core amount", "Provider amount", "Difference"}
DATE_LABELS = {"Core date", "Provider date"}
STATUS_LABELS = {"Core status", "Provider status"}

SOURCE_VIEW_COLUMNS = {
    "transaction_id": "Transaction ID",
    "reference": "Reference",
    "transaction_date": "Date",
    "amount": "Amount",
    "currency": "Currency",
    "status": "Status",
    "customer_name": "Customer",
    "description": "Description",
    "payment_method": "Payment method",
    "source_row": "CSV row",
}

REQUIRED_SCHEMA = "reference, amount, transaction_date, status"

st.set_page_config(
    page_title="LedgerMatch · Transaction Reconciliation",
    page_icon="🔁",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ink: #0f172a;
                --muted: #64748b;
                --line: #e2e8f0;
                --brand: #0f766e;
                --brand-soft: #ecfdf5;
                --paper: #ffffff;
                --canvas: #f8fafc;
            }
            .block-container {
                max-width: 1440px;
                padding-top: 2rem;
                padding-bottom: 4rem;
            }
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #f8fafc 0%, #ffffff 72%);
                border-right: 1px solid var(--line);
            }
            [data-testid="stSidebar"] > div:first-child {
                padding-top: 1.35rem;
            }
            #MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
            h1, h2, h3 { color: var(--ink); letter-spacing: -0.025em; }
            .brand-row {
                display: flex;
                align-items: center;
                gap: 0.65rem;
                margin-bottom: 1.5rem;
            }
            .brand-mark {
                width: 2rem;
                height: 2rem;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 8px;
                background: var(--ink);
                color: #ffffff;
                font-size: 0.72rem;
                font-weight: 800;
                letter-spacing: 0.04em;
            }
            .brand-name {
                font-weight: 750;
                color: var(--ink);
                font-size: 1.02rem;
            }
            .local-pill {
                margin-left: 0.15rem;
                border: 1px solid #ccfbf1;
                background: var(--brand-soft);
                color: #0f766e;
                border-radius: 999px;
                padding: 0.18rem 0.55rem;
                font-size: 0.66rem;
                font-weight: 750;
                letter-spacing: 0.07em;
            }
            .hero-title {
                margin: 0 0 0.55rem;
                font-size: clamp(2rem, 4vw, 2.85rem);
                line-height: 1.08;
                font-weight: 780;
                letter-spacing: -0.045em;
                color: var(--ink);
            }
            .hero-sub {
                max-width: 810px;
                margin: 0 0 1.2rem;
                color: var(--muted);
                font-size: 1rem;
                line-height: 1.65;
            }
            .side-brand {
                display: flex;
                align-items: center;
                gap: 0.55rem;
                font-size: 1.02rem;
                font-weight: 750;
                color: var(--ink);
                margin-bottom: 0.35rem;
            }
            .side-mark {
                width: 1.7rem;
                height: 1.7rem;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 7px;
                background: var(--brand);
                color: white;
                font-size: 0.64rem;
                font-weight: 800;
            }
            .side-copy {
                color: var(--muted);
                font-size: 0.87rem;
                line-height: 1.5;
                margin: 0 0 1.25rem;
            }
            .demo-card {
                background: #ffffff;
                border: 1px solid var(--line);
                border-radius: 12px;
                padding: 0.85rem 0.95rem;
                margin: 0.35rem 0 0.9rem;
            }
            .demo-card .mini-label {
                display: block;
                color: var(--brand);
                font-size: 0.64rem;
                font-weight: 800;
                letter-spacing: 0.1em;
                margin-bottom: 0.3rem;
            }
            .demo-card strong {
                display: block;
                color: var(--ink);
                font-size: 0.94rem;
                margin-bottom: 0.15rem;
            }
            .demo-card span.demo-detail {
                color: var(--muted);
                font-size: 0.8rem;
            }
            [data-testid="stMetric"] {
                background: var(--paper);
                border: 1px solid var(--line);
                border-radius: 14px;
                padding: 0.85rem 1rem;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.035);
            }
            [data-testid="stMetricLabel"] {
                color: var(--muted);
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.045em;
                text-transform: uppercase;
            }
            [data-testid="stMetricValue"] {
                color: var(--ink);
                font-size: 1.7rem;
                font-weight: 730;
            }
            [data-testid="stMetricDelta"] { font-size: 0.72rem; }
            .required-schema code {
                font-size: 0.75rem;
            }
            .legend {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin: 0.25rem 0 0.9rem;
            }
            .legend-item {
                display: inline-flex;
                align-items: center;
                gap: 0.37rem;
                color: var(--muted);
                font-size: 0.76rem;
                margin-right: 0.65rem;
            }
            .swatch {
                width: 0.7rem;
                height: 0.7rem;
                border-radius: 3px;
                display: inline-block;
                border: 1px solid rgba(15, 23, 42, 0.06);
            }
            .swatch.missing { background: #fff1f2; border-color: #fecdd3; }
            .swatch.duplicate { background: #fffbeb; border-color: #fde68a; }
            .swatch.mismatch { background: #fecaca; border-color: #fca5a5; }
            .swatch.field { background: #fef3c7; border-color: #fcd34d; }
            .empty-state {
                border: 1px dashed #cbd5e1;
                background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
                border-radius: 18px;
                padding: 2.6rem 2rem 2.2rem;
                text-align: center;
                margin: 0.4rem 0 1.5rem;
            }
            .empty-state .empty-icon {
                width: 3rem;
                height: 3rem;
                line-height: 3rem;
                margin: 0 auto 0.8rem;
                border-radius: 50%;
                background: var(--brand-soft);
                color: var(--brand);
                font-size: 1.4rem;
                font-weight: 700;
            }
            .empty-state h3 {
                margin: 0 0 0.4rem;
                font-size: 1.15rem;
            }
            .empty-state p {
                max-width: 610px;
                margin: 0 auto;
                color: var(--muted);
                font-size: 0.9rem;
                line-height: 1.6;
            }
            .feature-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 0.8rem;
                margin-top: 0.7rem;
            }
            .feature-card {
                border: 1px solid var(--line);
                border-radius: 12px;
                background: #ffffff;
                padding: 0.9rem 1rem;
            }
            .feature-card .feature-title {
                color: var(--ink);
                font-weight: 700;
                font-size: 0.85rem;
                margin-bottom: 0.18rem;
            }
            .feature-card .feature-copy {
                color: var(--muted);
                font-size: 0.78rem;
                line-height: 1.45;
            }
            .run-meta {
                color: var(--muted);
                font-size: 0.8rem;
                margin: -0.2rem 0 1rem;
            }
            .section-kicker {
                color: var(--brand);
                font-size: 0.68rem;
                font-weight: 800;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                margin-bottom: 0.15rem;
            }
            div[data-testid="stDownloadButton"] button {
                border-radius: 9px;
            }
            .stTabs [data-baseweb="tab-list"] {
                gap: 1.35rem;
                border-bottom: 1px solid var(--line);
            }
            .stTabs [data-baseweb="tab"] {
                padding-bottom: 0.7rem;
                font-weight: 650;
            }
            @media (max-width: 800px) {
                .feature-grid { grid-template-columns: 1fr; }
                .hero-title { font-size: 2rem; }
                .block-container { padding-top: 1.2rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    defaults: dict[str, Any] = {
        "recon_result": None,
        "last_run_id": None,
        "run_error": None,
        "report_payload": None,
        "report_warning": None,
        "save_warning": None,
        "db_warning": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state["db_warning"] is None:
        try:
            initialize_database()
        except Exception as exc:  # pragma: no cover - depends on local filesystem
            st.session_state["db_warning"] = (
                f"SQLite history is unavailable: {exc}. Reconciliation still works."
            )


def render_header() -> None:
    st.markdown(
        """
        <div class="brand-row">
            <span class="brand-mark">LM</span>
            <span class="brand-name">LedgerMatch</span>
            <span class="local-pill">LOCAL WORKSPACE</span>
        </div>
        <h1 class="hero-title">Transaction reconciliation</h1>
        <p class="hero-sub">
            Match core banking and payment provider exports by transaction reference,
            compare amounts, dates, and statuses, and send a clean audit trail to CSV
            or Excel. Everything runs locally on this machine.
        </p>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> tuple[str, Any, Any, bool]:
    with st.sidebar:
        st.markdown(
            """
            <div class="side-brand">
                <span class="side-mark">LM</span>
                <span>LedgerMatch</span>
            </div>
            <p class="side-copy">
                Upload two transaction exports and reconcile them in a single pass.
            </p>
            """,
            unsafe_allow_html=True,
        )

        mode = st.radio(
            "Data source",
            (UPLOAD_MODE, SAMPLE_MODE),
            help="Upload your own CSVs or run the built-in synthetic dataset.",
        )

        core_upload = None
        provider_upload = None
        if mode == UPLOAD_MODE:
            core_upload = st.file_uploader(
                "Core banking CSV",
                type=["csv"],
                key="core_upload",
                help="CSV containing reference, amount, transaction_date, and status.",
            )
            provider_upload = st.file_uploader(
                "Payment provider CSV",
                type=["csv"],
                key="provider_upload",
                help="CSV containing reference, amount, transaction_date, and status.",
            )
        else:
            st.markdown(
                """
                <div class="demo-card">
                    <span class="mini-label">DEMO DATASET</span>
                    <strong>14 core · 14 provider records</strong>
                    <span class="demo-detail">
                        Seven exact matches and seven intentional discrepancies,
                        including missing, duplicate, and field-mismatch cases.
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        run_clicked = st.button(
            "Run reconciliation",
            type="primary",
            width="stretch",
            key="run_reconciliation",
        )

        with st.expander("CSV schema & matching rules"):
            st.markdown(
                f"""
                Both files need a reference, amount, date, and status column:
                `{REQUIRED_SCHEMA}`

                Accepted aliases include `transaction_reference`, `transaction_amount`,
                `date` / `posted_date`, and `transaction_status`.

                Rows are matched on the exact reference after trimming whitespace.
                Amounts are compared to the cent, dates by calendar day, and statuses
                case-insensitively. Duplicate references are flagged, not silently
                matched. Optional columns: `transaction_id`, `currency`,
                `customer_name`, `description`, and `payment_method`.
                """
            )

        if st.session_state.get("db_warning"):
            st.warning(st.session_state["db_warning"])

        st.caption("Local-only processing · no transaction data leaves this machine.")

    return mode, core_upload, provider_upload, run_clicked


def _set_error(
    message: str,
    *,
    missing_columns: list[str] | None = None,
    row_issues: list[dict[str, Any]] | None = None,
) -> None:
    st.session_state["run_error"] = {
        "message": message,
        "missing_columns": missing_columns or [],
        "row_issues": row_issues or [],
    }


def _prepare_reports(result: ReconciliationResult) -> None:
    payload: dict[str, bytes] = {}
    failures: list[str] = []
    try:
        payload["excel"] = build_excel_report(result)
    except Exception as exc:  # pragma: no cover - defensive fallback
        failures.append(f"Excel ({exc})")
    try:
        payload["csv"] = build_csv_report(result)
    except Exception as exc:  # pragma: no cover - defensive fallback
        failures.append(f"CSV ({exc})")
    try:
        payload["discrepancies_csv"] = build_csv_report(
            result, discrepancies_only=True
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        failures.append(f"discrepancies CSV ({exc})")

    st.session_state["report_payload"] = payload
    st.session_state["report_warning"] = (
        "Some report formats could not be produced: " + "; ".join(failures)
        if failures
        else None
    )


def handle_run(mode: str, core_upload: Any, provider_upload: Any) -> None:
    st.session_state["recon_result"] = None
    st.session_state["last_run_id"] = None
    st.session_state["run_error"] = None
    st.session_state["report_payload"] = None
    st.session_state["report_warning"] = None
    st.session_state["save_warning"] = None

    if mode == UPLOAD_MODE:
        if core_upload is None or provider_upload is None:
            _set_error(
                "Upload both CSV files before running reconciliation: one core "
                "banking export and one payment provider export."
            )
            return
        core_source = core_upload.getvalue()
        provider_source = provider_upload.getvalue()
        core_filename = core_upload.name
        provider_filename = provider_upload.name
    else:
        try:
            core_source = SAMPLE_CORE.read_bytes()
            provider_source = SAMPLE_PROVIDER.read_bytes()
        except OSError as exc:
            _set_error(f"The built-in sample files could not be read: {exc}")
            return
        core_filename = SAMPLE_CORE.name
        provider_filename = SAMPLE_PROVIDER.name

    try:
        with st.spinner("Validating files and matching transaction references…"):
            result = reconcile_files(
                core_source,
                provider_source,
                core_filename=core_filename,
                provider_filename=provider_filename,
            )
            _prepare_reports(result)
    except CSVValidationError as exc:
        _set_error(
            str(exc),
            missing_columns=exc.missing_columns,
            row_issues=[dataclasses.asdict(issue) for issue in exc.row_issues],
        )
        return
    except Exception as exc:  # pragma: no cover - defensive fallback
        _set_error(f"Reconciliation could not be completed: {exc}")
        return

    st.session_state["recon_result"] = result

    try:
        st.session_state["last_run_id"] = save_reconciliation(result)
    except Exception as exc:  # pragma: no cover - depends on local filesystem
        st.session_state["save_warning"] = (
            f"The reconciliation completed, but this run was not saved to SQLite "
            f"history: {exc}"
        )


def render_error() -> None:
    error = st.session_state.get("run_error")
    if not error:
        return

    st.error(error["message"])
    if error.get("missing_columns"):
        st.info(
            "Required columns are: reference, amount, transaction_date, and status. "
            "Common aliases are accepted; check the sidebar for details."
        )
    if error.get("row_issues"):
        issues = pd.DataFrame(error["row_issues"]).rename(
            columns={"row_number": "CSV row", "column": "Column", "message": "Issue"}
        )
        with st.expander("Review invalid values", expanded=True):
            st.dataframe(
                issues.head(50),
                width="stretch",
                hide_index=True,
            )
            if len(issues) > 50:
                st.caption(f"Showing the first 50 of {len(issues)} issues.")


def render_empty_state(mode: str) -> None:
    if mode == SAMPLE_MODE:
        prompt = (
            "The synthetic demo dataset is ready. Click <strong>Run reconciliation</strong> "
            "in the sidebar to reveal the matched, missing, duplicate, and mismatched records."
        )
    else:
        prompt = (
            "Upload your core banking and payment provider CSV files in the sidebar, "
            "then click <strong>Run reconciliation</strong>. Or switch the data source to "
            "the built-in sample to explore a completed run."
        )

    st.markdown(
        f"""
        <div class="empty-state">
            <div class="empty-icon">⇄</div>
            <h3>No reconciliation loaded</h3>
            <p>{prompt}</p>
        </div>
        <div class="feature-grid">
            <div class="feature-card">
                <div class="feature-title">Reference-key matching</div>
                <div class="feature-copy">
                    Exact reference IDs are aligned across both systems, with
                    duplicates surfaced instead of forced into a match.
                </div>
            </div>
            <div class="feature-card">
                <div class="feature-title">Three-way checks</div>
                <div class="feature-copy">
                    Amounts are compared to the cent; dates by calendar day; statuses
                    case-insensitively. Every mismatch is visible.
                </div>
            </div>
            <div class="feature-card">
                <div class="feature-title">Audit-ready output</div>
                <div class="feature-copy">
                    Download a styled Excel workbook or CSV, and keep a local SQLite
                    history of each reconciliation run.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Required CSV structure", expanded=False):
        st.markdown(
            "Each file needs the following columns. Header matching is "
            "case-insensitive and common aliases are accepted."
        )
        st.code(REQUIRED_SCHEMA, language="text")
        st.caption(
            "Optional columns: transaction_id, currency, customer_name, description, "
            "payment_method. Amounts may include commas or common currency symbols."
        )


def _format_optional_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.2f}"


def _result_view(details: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in RESULT_VIEW_COLUMNS if column in details.columns]
    view = details[columns].rename(columns=RESULT_VIEW_COLUMNS)
    for label in ("Core amount", "Provider amount", "Difference"):
        if label in view.columns:
            view[label] = pd.to_numeric(view[label], errors="coerce").map(
                _format_optional_money
            )
    for label in view.columns:
        if label not in {"Core amount", "Provider amount", "Difference"}:
            view[label] = view[label].where(view[label].notna(), "—")
    return view


def _row_styles(row: pd.Series) -> list[str]:
    result = row.get("Result")
    base = ""
    if result in MISSING_RESULTS:
        base = "background-color: #FFF1F2; color: #9F1239;"
    elif result in DUPLICATE_RESULTS:
        base = "background-color: #FFFBEB; color: #92400E;"

    styles = [base] * len(row)
    fields = str(row.get("Mismatch") or "")
    if "Amount" in fields:
        for label in AMOUNT_LABELS:
            if label in row.index:
                styles[row.index.get_loc(label)] = (
                    "background-color: #FECACA; color: #991B1B; font-weight: 700;"
                )
    if "Date" in fields:
        for label in DATE_LABELS:
            if label in row.index:
                styles[row.index.get_loc(label)] = (
                    "background-color: #FEF3C7; color: #92400E; font-weight: 600;"
                )
    if "Status" in fields:
        for label in STATUS_LABELS:
            if label in row.index:
                styles[row.index.get_loc(label)] = (
                    "background-color: #FEF3C7; color: #92400E; font-weight: 600;"
                )
    return styles


def _styled_table(details: pd.DataFrame) -> Any:
    view = _result_view(details)
    formatters = {
        "Core recs": "{:d}",
        "Provider recs": "{:d}",
    }
    return (
        view.style.apply(_row_styles, axis=1)
        .format(formatters, na_rep="—")
        .set_properties(**{"font-size": "0.82rem"})
    )


def _render_legend() -> None:
    st.markdown(
        """
        <div class="legend">
            <span class="legend-item"><span class="swatch missing"></span>Missing record</span>
            <span class="legend-item"><span class="swatch duplicate"></span>Duplicate reference</span>
            <span class="legend-item"><span class="swatch mismatch"></span>Amount mismatch</span>
            <span class="legend-item"><span class="swatch field"></span>Date / status mismatch</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _table_height(row_count: int) -> int:
    return min(620, max(190, 38 * (row_count + 1)))


def render_reports(result: ReconciliationResult) -> None:
    payload = st.session_state.get("report_payload") or {}
    if st.session_state.get("report_warning"):
        st.warning(st.session_state["report_warning"])
    if not payload:
        st.info("Report files are not available for this run.")
        return

    timestamp = result.generated_at.strftime("%Y%m%d_%H%M%S")
    st.markdown('<div class="section-kicker">Exports</div>', unsafe_allow_html=True)
    st.markdown("##### Download reconciliation reports")
    st.caption(
        "The Excel workbook includes a summary, all results, discrepancies, matched "
        "references, and both source datasets. CSV exports include the full result set."
    )
    download_columns = st.columns(3)
    with download_columns[0]:
        if "excel" in payload:
            st.download_button(
                "Excel workbook (.xlsx)",
                data=payload["excel"],
                file_name=f"reconciliation_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key="download_excel",
            )
    with download_columns[1]:
        if "csv" in payload:
            st.download_button(
                "Reconciliation CSV",
                data=payload["csv"],
                file_name=f"reconciliation_{timestamp}.csv",
                mime="text/csv",
                width="stretch",
                key="download_csv",
            )
    with download_columns[2]:
        if "discrepancies_csv" in payload:
            st.download_button(
                "Discrepancies CSV",
                data=payload["discrepancies_csv"],
                file_name=f"reconciliation_discrepancies_{timestamp}.csv",
                mime="text/csv",
                width="stretch",
                key="download_discrepancies_csv",
            )


def render_discrepancy_tab(result: ReconciliationResult) -> None:
    discrepancies = result.discrepancies
    if discrepancies.empty:
        st.success("No discrepancies found. Every reference matched exactly.")
        return

    filter_columns = st.columns([2.2, 1.7, 1.0])
    with filter_columns[0]:
        query = st.text_input(
            "Search",
            placeholder="Reference, transaction ID, customer, or note",
            key="discrepancy_search",
        )
    with filter_columns[1]:
        selected_types = st.multiselect(
            "Discrepancy type",
            options=[result for result in DISCREPANCY_TYPES if result in set(discrepancies["result"])],
            default=[result for result in DISCREPANCY_TYPES if result in set(discrepancies["result"])],
            key="discrepancy_types",
        )
    with filter_columns[2]:
        amount_only = st.checkbox(
            "Amount only",
            help="Show only records where the transaction amount differs.",
            key="amount_only",
        )

    filtered = discrepancies[discrepancies["result"].isin(selected_types)]
    if amount_only:
        filtered = filtered[
            filtered["mismatch_fields"].fillna("").str.contains("Amount", regex=False)
        ]

    if query.strip():
        search_columns = [
            "reference",
            "core_transaction_id",
            "provider_transaction_id",
            "core_customer",
            "provider_customer",
            "core_status",
            "provider_status",
            "note",
        ]
        haystack = (
            filtered[search_columns]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.casefold()
        )
        filtered = filtered[haystack.str.contains(query.strip().casefold(), regex=False)]

    st.caption(
        f"Showing {len(filtered)} of {len(discrepancies)} discrepancy cases. "
        "Missing references are shaded; mismatched amount cells are highlighted."
    )
    _render_legend()

    if filtered.empty:
        st.info("No discrepancies match the current filters.")
        return

    st.dataframe(
        _styled_table(filtered),
        width="stretch",
        hide_index=True,
        height=_table_height(len(filtered)),
    )


def render_matched_tab(result: ReconciliationResult) -> None:
    matched = result.matched
    if matched.empty:
        st.info("No exact matches were found in this run.")
        return
    st.caption(
        f"{len(matched)} references matched exactly on amount, date, and status."
    )
    st.dataframe(
        _result_view(matched),
        width="stretch",
        hide_index=True,
        height=_table_height(len(matched)),
    )


def render_source_tab(result: ReconciliationResult) -> None:
    for title, frame, filename in (
        ("Core banking records", result.core, result.core_filename),
        ("Payment provider records", result.provider, result.provider_filename),
    ):
        st.markdown(f"##### {title}")
        st.caption(f"{len(frame)} rows · {filename}")
        columns = [column for column in SOURCE_VIEW_COLUMNS if column in frame.columns]
        view = frame[columns].rename(columns=SOURCE_VIEW_COLUMNS)
        st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            height=_table_height(len(view)),
        )


def render_results(result: ReconciliationResult) -> None:
    summary = result.summary
    run_id = st.session_state.get("last_run_id")
    generated = result.generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run_text = f"Run #{run_id}" if run_id else "Unsaved run"

    st.markdown('<div class="section-kicker">Reconciliation results</div>', unsafe_allow_html=True)
    st.markdown("### Summary")
    st.caption(
        f"{result.core_filename}  ·  {result.provider_filename}  ·  "
        f"{run_text}  ·  generated {generated}"
    )

    if st.session_state.get("save_warning"):
        st.warning(st.session_state["save_warning"])

    first_metrics = st.columns(3)
    first_metrics[0].metric(
        "Total transactions",
        f"{summary['total_transactions']:,}",
        help="Rows across both source files, including duplicate records.",
    )
    first_metrics[1].metric(
        "Matched records",
        f"{summary['matched']:,}",
        help="References matched exactly on amount, date, and status.",
    )
    first_metrics[2].metric(
        "Total discrepancies",
        f"{summary['discrepancies']:,}",
        help="All non-exact-match reference cases.",
    )

    second_metrics = st.columns(3)
    second_metrics[0].metric(
        "Amount mismatches",
        f"{summary['amount_mismatches']:,}",
        help="Mismatched references where the amount differs.",
    )
    second_metrics[1].metric(
        "Missing records",
        f"{summary['missing_total']:,}",
        help="References found in only one of the two files.",
    )
    second_metrics[2].metric(
        "Duplicate references",
        f"{summary['duplicates']:,}",
        help="References with more than one record in either source.",
    )

    st.progress(min(max(float(summary["match_rate"]) / 100, 0.0), 1.0))
    st.caption(
        f"**{summary['match_rate']:.1f}% exact match rate** · "
        f"{summary['matched']} of {summary['unique_references']} references. "
        f"{summary['core_transactions']} core records + "
        f"{summary['provider_transactions']} provider records. "
        f"Date mismatches: {summary['date_mismatches']} · "
        f"status mismatches: {summary['status_mismatches']}."
    )

    st.divider()
    render_reports(result)
    st.divider()

    detail_tabs = st.tabs(
        [
            f"Discrepancies ({len(result.discrepancies)})",
            f"Matched ({len(result.matched)})",
            "Source records",
        ]
    )
    with detail_tabs[0]:
        render_discrepancy_tab(result)
    with detail_tabs[1]:
        render_matched_tab(result)
    with detail_tabs[2]:
        render_source_tab(result)


def render_history() -> None:
    st.markdown('<div class="section-kicker">Audit trail</div>', unsafe_allow_html=True)
    st.markdown("### Run history")
    st.caption(
        "Every completed run is stored in the local SQLite database "
        "(data/reconciliation.db) and can be reviewed below."
    )

    if st.session_state.get("db_warning"):
        st.warning(st.session_state["db_warning"])
        return

    try:
        runs = list_runs(limit=25)
    except Exception as exc:  # pragma: no cover - depends on local filesystem
        st.error(f"Run history could not be loaded: {exc}")
        return

    if runs.empty:
        st.info("No reconciliation runs yet. Complete a run to start the audit trail.")
        return

    history_view = runs[
        [
            "run_id",
            "created_at",
            "core_filename",
            "provider_filename",
            "total_transactions",
            "matched",
            "discrepancies",
            "amount_mismatches",
            "missing_total",
            "duplicates",
        ]
    ].copy()
    history_view["created_at"] = history_view["created_at"].map(format_utc_timestamp)
    history_view = history_view.rename(
        columns={
            "run_id": "Run",
            "created_at": "Completed (UTC)",
            "core_filename": "Core file",
            "provider_filename": "Provider file",
            "total_transactions": "Transactions",
            "matched": "Matched",
            "discrepancies": "Discrepancies",
            "amount_mismatches": "Amount mismatches",
            "missing_total": "Missing",
            "duplicates": "Duplicates",
        }
    )
    st.dataframe(
        history_view,
        width="stretch",
        hide_index=True,
        height=_table_height(len(history_view)),
    )

    options = {
        int(row.run_id): (
            f"Run #{int(row.run_id)} · {format_utc_timestamp(row.created_at)} · "
            f"{int(row.matched)} matched / {int(row.discrepancies)} discrepancies"
        )
        for row in runs.itertuples()
    }
    selected = st.selectbox(
        "Inspect a saved run",
        options=list(options),
        format_func=options.get,
        key="history_run_select",
    )
    saved = get_run(int(selected)) if selected is not None else None
    if saved is None:
        st.error("That saved run could not be loaded.")
        return

    st.markdown("#### Snapshot")
    st.caption(
        f"{saved.core_filename} · {saved.provider_filename} · "
        f"{format_utc_timestamp(saved.created_at)}"
    )
    snapshot = saved.summary or {}
    columns = st.columns(5)
    columns[0].metric("Transactions", f"{snapshot.get('total_transactions', 0):,}")
    columns[1].metric("Matched", f"{snapshot.get('matched', 0):,}")
    columns[2].metric("Discrepancies", f"{snapshot.get('discrepancies', 0):,}")
    columns[3].metric("Missing", f"{snapshot.get('missing_total', 0):,}")
    columns[4].metric("Duplicates", f"{snapshot.get('duplicates', 0):,}")

    stored_discrepancies = saved.details[
        saved.details["result"] != RESULT_MATCHED
    ].copy()
    if stored_discrepancies.empty:
        st.success("This saved run had no discrepancies.")
    else:
        st.markdown("##### Stored discrepancies")
        st.dataframe(
            _styled_table(stored_discrepancies),
            width="stretch",
            hide_index=True,
            height=_table_height(len(stored_discrepancies)),
        )


def render_guide() -> None:
    st.markdown('<div class="section-kicker">Method</div>', unsafe_allow_html=True)
    st.markdown("### How matching works")
    st.markdown(
        """
        Transactions are grouped by **reference** after trimming surrounding whitespace.
        A reference is compared only when it appears exactly once in both files.

        - **Matched** — a single core record and a single provider record agree on
          amount, calendar date, and status.
        - **Mismatched** — both records exist, but one or more compared fields differ.
        - **Missing in core / Missing in provider** — the reference exists in only one file.
        - **Duplicate** — a reference appears more than once in at least one file. The
          duplicate case is flagged instead of arbitrarily choosing a record.
        """
    )

    column_a, column_b = st.columns(2)
    with column_a:
        st.markdown("#### Input contract")
        st.code(REQUIRED_SCHEMA, language="text")
        st.markdown(
            """
            Required canonical columns are `reference`, `amount`,
            `transaction_date`, and `status`. Common aliases such as
            `transaction_reference`, `transaction_amount`, `date`, `posted_date`,
            and `transaction_status` are mapped automatically.

            Amounts are parsed to integer cents. Parentheses and common currency
            symbols are supported. Dates are normalised to `YYYY-MM-DD`. Statuses
            are compared case-insensitively.
            """
        )
    with column_b:
        st.markdown("#### Built-in sample")
        st.markdown(
            """
            The demo contains **14 core records** and **14 provider records**
            covering **14 references**:

            - 7 exact matches
            - 1 amount mismatch, 1 date mismatch, and 1 status mismatch
            - 1 missing in provider and 1 missing in core
            - 1 duplicate reference in each source

            Expected result: **7 discrepancies** and a **50% exact match rate**.
            """
        )

    st.markdown("#### Data quality behavior")
    st.markdown(
        """
        Unreadable files, missing required columns, blank references, invalid
        amounts, unparseable dates, and blank statuses are rejected with a clear
        error rather than silently dropped. The upload check is designed to fail
        closed so a reconciliation is never generated from partial data.
        """
    )


def main() -> None:
    inject_styles()
    init_state()
    render_header()
    mode, core_upload, provider_upload, run_clicked = render_sidebar()

    if run_clicked:
        handle_run(mode, core_upload, provider_upload)

    workspace_tab, history_tab, guide_tab = st.tabs(
        ["Reconciliation", "Run history", "How it works"]
    )
    with workspace_tab:
        render_error()
        result = st.session_state.get("recon_result")
        if result is None:
            render_empty_state(mode)
        else:
            render_results(result)
    with history_tab:
        render_history()
    with guide_tab:
        render_guide()


if __name__ == "__main__":
    main()
