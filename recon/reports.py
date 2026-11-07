"""CSV and Excel export builders for reconciliation results."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from recon.engine import (
    DETAIL_COLUMNS,
    RESULT_DUP_BOTH,
    RESULT_DUP_CORE,
    RESULT_DUP_PROVIDER,
    RESULT_MISMATCHED,
    RESULT_MISSING_CORE,
    RESULT_MISSING_PROVIDER,
    ReconciliationResult,
)

DETAIL_LABELS = {
    "result": "Result",
    "reference": "Reference",
    "core_transaction_id": "Core transaction ID",
    "provider_transaction_id": "Provider transaction ID",
    "core_amount": "Core amount",
    "provider_amount": "Provider amount",
    "amount_difference": "Difference (provider - core)",
    "core_date": "Core date",
    "provider_date": "Provider date",
    "core_status": "Core status",
    "provider_status": "Provider status",
    "core_currency": "Core currency",
    "provider_currency": "Provider currency",
    "core_customer": "Core customer",
    "provider_customer": "Provider customer",
    "core_count": "Core records",
    "provider_count": "Provider records",
    "mismatch_fields": "Mismatch fields",
    "note": "Review note",
}

SOURCE_LABELS = {
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

DUPLICATE_RESULTS = {RESULT_DUP_BOTH, RESULT_DUP_CORE, RESULT_DUP_PROVIDER}
MISSING_RESULTS = {RESULT_MISSING_CORE, RESULT_MISSING_PROVIDER}

HEADER_FILL = PatternFill("solid", fgColor="0F172A")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
SUBTLE_FILL = PatternFill("solid", fgColor="F1F5F9")
SECTION_FONT = Font(color="0F172A", bold=True, size=11)
MISSING_FILL = PatternFill("solid", fgColor="FFF1F2")
MISSING_FONT = Font(color="9F1239")
DUPLICATE_FILL = PatternFill("solid", fgColor="FFFBEB")
DUPLICATE_FONT = Font(color="92400E")
AMOUNT_MISMATCH_FILL = PatternFill("solid", fgColor="FECACA")
AMOUNT_MISMATCH_FONT = Font(color="991B1B", bold=True)
FIELD_MISMATCH_FILL = PatternFill("solid", fgColor="FEF3C7")
FIELD_MISMATCH_FONT = Font(color="92400E")
THIN_BORDER = Border(bottom=Side(style="thin", color="E2E8F0"))
FORMULA_PREFIXES = ("=", "+", "-", "@")


def _human_detail_frame(details: pd.DataFrame) -> pd.DataFrame:
    view = details.reindex(columns=DETAIL_COLUMNS).rename(columns=DETAIL_LABELS)
    return view


def _human_source_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in SOURCE_LABELS if column in frame.columns]
    return frame[columns].rename(columns=SOURCE_LABELS)


def _safe_text(value: str) -> str:
    """Neutralise spreadsheet formula injection in textual fields."""

    if value and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _sanitised_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
    view = frame.copy()
    for column in view.columns:
        if pd.api.types.is_object_dtype(view[column]) or pd.api.types.is_string_dtype(
            view[column]
        ):
            view[column] = view[column].map(
                lambda value: _safe_text(value) if isinstance(value, str) else value
            )
    return view


def build_csv_report(
    result: ReconciliationResult, *, discrepancies_only: bool = False
) -> bytes:
    """Build a UTF-8 CSV report from reconciliation detail rows."""

    details = result.discrepancies if discrepancies_only else result.details
    view = _sanitised_for_csv(_human_detail_frame(details))
    return view.to_csv(index=False, na_rep="").encode("utf-8-sig")


def _excel_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return _safe_text(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def _write_table(
    worksheet: Worksheet,
    frame: pd.DataFrame,
    *,
    start_row: int = 1,
    highlight_results: bool = False,
) -> tuple[int, int]:
    """Write a DataFrame to a sheet and return (header row, last row)."""

    columns = list(frame.columns)
    for column_index, label in enumerate(columns, start=1):
        cell = worksheet.cell(row=start_row, column=column_index, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
        cell.border = THIN_BORDER
    worksheet.row_dimensions[start_row].height = 22

    for row_index, record in enumerate(frame.to_dict(orient="records"), start=start_row + 1):
        result_value = record.get(DETAIL_LABELS["result"])
        mismatch_fields = str(record.get(DETAIL_LABELS["mismatch_fields"]) or "")
        for column_index, column in enumerate(columns, start=1):
            cell = worksheet.cell(
                row=row_index, column=column_index, value=_excel_value(record.get(column))
            )
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=column in {
                DETAIL_LABELS["note"],
                DETAIL_LABELS["mismatch_fields"],
            })

            if highlight_results:
                if result_value in MISSING_RESULTS:
                    cell.fill = MISSING_FILL
                    cell.font = MISSING_FONT
                elif result_value in DUPLICATE_RESULTS:
                    cell.fill = DUPLICATE_FILL
                    cell.font = DUPLICATE_FONT
                elif result_value == RESULT_MISMATCHED:
                    if "Amount" in mismatch_fields and column in {
                        DETAIL_LABELS["core_amount"],
                        DETAIL_LABELS["provider_amount"],
                        DETAIL_LABELS["amount_difference"],
                    }:
                        cell.fill = AMOUNT_MISMATCH_FILL
                        cell.font = AMOUNT_MISMATCH_FONT
                    elif "Date" in mismatch_fields and column in {
                        DETAIL_LABELS["core_date"],
                        DETAIL_LABELS["provider_date"],
                    }:
                        cell.fill = FIELD_MISMATCH_FILL
                        cell.font = FIELD_MISMATCH_FONT
                    elif "Status" in mismatch_fields and column in {
                        DETAIL_LABELS["core_status"],
                        DETAIL_LABELS["provider_status"],
                    }:
                        cell.fill = FIELD_MISMATCH_FILL
                        cell.font = FIELD_MISMATCH_FONT

            if column in {
                DETAIL_LABELS["core_amount"],
                DETAIL_LABELS["provider_amount"],
                DETAIL_LABELS["amount_difference"],
                SOURCE_LABELS["amount"],
            }:
                cell.number_format = '#,##0.00;[Red]-#,##0.00'

    last_row = start_row + len(frame)
    if len(frame):
        worksheet.freeze_panes = f"A{start_row + 1}"
        worksheet.auto_filter.ref = (
            f"A{start_row}:{get_column_letter(len(columns))}{last_row}"
        )
    return start_row, last_row


def _write_title(
    worksheet: Worksheet, title: str, subtitle: str, width: int = 6
) -> None:
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    title_cell = worksheet.cell(row=1, column=1, value=title)
    title_cell.font = Font(color="FFFFFF", bold=True, size=16)
    title_cell.fill = PatternFill("solid", fgColor="0F766E")
    title_cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 30

    worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    subtitle_cell = worksheet.cell(row=2, column=1, value=subtitle)
    subtitle_cell.font = Font(color="475569", size=10)
    subtitle_cell.alignment = Alignment(vertical="center")


def _autosize(worksheet: Worksheet, minimum: int = 10, maximum: int = 42) -> None:
    for column_cells in worksheet.columns:
        length = max(
            (
                len(str(cell.value)) if cell.value is not None else 0
                for cell in column_cells
            ),
            default=0,
        )
        letter = get_column_letter(column_cells[0].column)
        worksheet.column_dimensions[letter].width = min(max(length + 2, minimum), maximum)


def _build_summary_sheet(worksheet: Worksheet, result: ReconciliationResult) -> None:
    summary = result.summary
    generated_at = result.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    _write_title(
        worksheet,
        "Transaction Reconciliation Report",
        f"Generated {generated_at} · LedgerMatch",
    )
    worksheet.sheet_view.showGridLines = False

    worksheet["A4"] = "Core banking file"
    worksheet["B4"] = _safe_text(result.core_filename)
    worksheet["A5"] = "Payment provider file"
    worksheet["B5"] = _safe_text(result.provider_filename)

    for row in (4, 5):
        worksheet[f"A{row}"].font = Font(color="64748B", size=10)
        worksheet[f"B{row}"].font = Font(color="0F172A", size=10)

    worksheet["A7"] = "Reconciliation summary"
    worksheet["A7"].font = SECTION_FONT
    headers = ["Metric", "Value"]
    for column, label in enumerate(headers, start=1):
        cell = worksheet.cell(row=8, column=column, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    metrics = [
        ("Total transactions", summary["total_transactions"]),
        ("Core banking records", summary["core_transactions"]),
        ("Payment provider records", summary["provider_transactions"]),
        ("Unique references", summary["unique_references"]),
        ("Matched references", summary["matched"]),
        ("Total discrepancies", summary["discrepancies"]),
        ("Match rate", f"{summary['match_rate']:.1f}%"),
        ("Amount mismatches", summary["amount_mismatches"]),
        ("Date mismatches", summary["date_mismatches"]),
        ("Status mismatches", summary["status_mismatches"]),
        ("Missing in core", summary["missing_in_core"]),
        ("Missing in provider", summary["missing_in_provider"]),
        ("Duplicate references", summary["duplicates"]),
        ("Extra duplicate records", summary["duplicate_extra_records"]),
    ]
    for index, (label, value) in enumerate(metrics, start=9):
        worksheet.cell(row=index, column=1, value=label).border = THIN_BORDER
        value_cell = worksheet.cell(row=index, column=2, value=value)
        value_cell.border = THIN_BORDER
        value_cell.font = Font(bold=label in {"Total discrepancies", "Matched references"})
        if label == "Total discrepancies" and int(summary["discrepancies"]) > 0:
            value_cell.fill = MISSING_FILL
            value_cell.font = Font(color="9F1239", bold=True)

    breakdown_start = len(metrics) + 11
    worksheet.cell(row=breakdown_start, column=1, value="Result breakdown").font = (
        SECTION_FONT
    )
    worksheet.cell(row=breakdown_start + 1, column=1, value="Result").fill = HEADER_FILL
    worksheet.cell(row=breakdown_start + 1, column=1).font = HEADER_FONT
    worksheet.cell(row=breakdown_start + 1, column=2, value="References").fill = HEADER_FILL
    worksheet.cell(row=breakdown_start + 1, column=2).font = HEADER_FONT

    breakdown = result.details["result"].value_counts()
    for index, (label, count) in enumerate(breakdown.items(), start=breakdown_start + 2):
        worksheet.cell(row=index, column=1, value=label).border = THIN_BORDER
        cell = worksheet.cell(row=index, column=2, value=int(count))
        cell.border = THIN_BORDER
        if label in MISSING_RESULTS:
            cell.fill = MISSING_FILL
        elif label in DUPLICATE_RESULTS:
            cell.fill = DUPLICATE_FILL

    worksheet.column_dimensions["A"].width = 29
    worksheet.column_dimensions["B"].width = 48


def build_excel_report(result: ReconciliationResult) -> bytes:
    """Build a styled multi-sheet Excel reconciliation workbook."""

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    _build_summary_sheet(summary_sheet, result)

    details = _human_detail_frame(result.details)
    all_sheet = workbook.create_sheet("Reconciliation")
    _write_table(all_sheet, details, highlight_results=True)
    all_sheet.sheet_properties.tabColor = "0F766E"

    discrepancy_sheet = workbook.create_sheet("Discrepancies")
    discrepancy_details = _human_detail_frame(result.discrepancies)
    _write_table(discrepancy_sheet, discrepancy_details, highlight_results=True)
    discrepancy_sheet.sheet_properties.tabColor = "B91C1C"

    matched_sheet = workbook.create_sheet("Matched")
    _write_table(matched_sheet, _human_detail_frame(result.matched))
    matched_sheet.sheet_properties.tabColor = "15803D"

    core_sheet = workbook.create_sheet("Core Banking")
    _write_table(core_sheet, _human_source_frame(result.core))
    core_sheet.sheet_properties.tabColor = "0E7490"

    provider_sheet = workbook.create_sheet("Payment Provider")
    _write_table(provider_sheet, _human_source_frame(result.provider))
    provider_sheet.sheet_properties.tabColor = "7C3AED"

    for sheet in (
        all_sheet,
        discrepancy_sheet,
        matched_sheet,
        core_sheet,
        provider_sheet,
    ):
        _autosize(sheet)
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = True
        sheet.row_dimensions[1].height = 22

    workbook.properties.title = "Transaction Reconciliation Report"
    workbook.properties.subject = (
        f"{result.core_filename} vs {result.provider_filename}"
    )
    workbook.properties.creator = "LedgerMatch"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
