"""Tests for CSV ingestion, matching, persistence, and report exports."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from recon.db import get_run, list_runs, save_reconciliation
from recon.engine import (
    CSVValidationError,
    RESULT_DUP_CORE,
    RESULT_DUP_PROVIDER,
    RESULT_MATCHED,
    RESULT_MISMATCHED,
    RESULT_MISSING_CORE,
    RESULT_MISSING_PROVIDER,
    load_transactions,
    reconcile_files,
    reconcile_transactions,
)
from recon.reports import build_csv_report, build_excel_report

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"
SAMPLE_CORE = SAMPLE_DIR / "core_banking_transactions.csv"
SAMPLE_PROVIDER = SAMPLE_DIR / "payment_provider_transactions.csv"

HEADER = "transaction_id,reference,transaction_date,amount,status"


def csv_text(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def reconcile_texts(core_csv: str, provider_csv: str):
    return reconcile_files(
        io.StringIO(core_csv),
        io.StringIO(provider_csv),
        core_filename="core.csv",
        provider_filename="provider.csv",
    )


def test_sample_dataset_reconciles_to_expected_counts() -> None:
    result = reconcile_files(SAMPLE_CORE, SAMPLE_PROVIDER)

    assert result.summary["total_transactions"] == 28
    assert result.summary["core_transactions"] == 14
    assert result.summary["provider_transactions"] == 14
    assert result.summary["unique_references"] == 14
    assert result.summary["matched"] == 7
    assert result.summary["discrepancies"] == 7
    assert result.summary["amount_mismatches"] == 1
    assert result.summary["date_mismatches"] == 1
    assert result.summary["status_mismatches"] == 1
    assert result.summary["missing_total"] == 2
    assert result.summary["duplicates"] == 2
    assert result.summary["match_rate"] == 50.0
    assert len(result.discrepancies) == 7


def test_amount_mismatch_is_flagged_with_signed_difference() -> None:
    core = csv_text("C-1,TXN-1,2025-05-01,100.00,COMPLETED")
    provider = csv_text("P-1,TXN-1,2025-05-01,99.99,COMPLETED")

    result = reconcile_texts(core, provider)
    row = result.details.iloc[0]

    assert row["result"] == RESULT_MISMATCHED
    assert row["mismatch_fields"] == "Amount"
    assert row["amount_difference"] == pytest.approx(-0.01)
    assert result.summary["amount_mismatches"] == 1
    assert result.summary["matched"] == 0


def test_date_and_status_mismatches_are_both_reported() -> None:
    core = csv_text("C-1,TXN-2,2025-05-01,42.00,PENDING")
    provider = csv_text("P-1,TXN-2,2025-05-02,42.00,FAILED")

    result = reconcile_texts(core, provider)
    row = result.details.iloc[0]

    assert row["result"] == RESULT_MISMATCHED
    assert set(str(row["mismatch_fields"]).split(", ")) == {"Date", "Status"}
    assert result.summary["date_mismatches"] == 1
    assert result.summary["status_mismatches"] == 1


def test_status_comparison_is_case_insensitive() -> None:
    core = csv_text("C-1,TXN-3,2025-05-01,42.00,COMPLETED")
    provider = csv_text("P-1,TXN-3,2025-05-01,42.00,completed")

    result = reconcile_texts(core, provider)

    assert result.details.iloc[0]["result"] == RESULT_MATCHED
    assert result.summary["status_mismatches"] == 0


def test_missing_transactions_are_identified_in_both_directions() -> None:
    core = csv_text(
        "C-1,TXN-10,2025-05-01,10.00,COMPLETED",
        "C-2,TXN-11,2025-05-01,11.00,COMPLETED",
    )
    provider = csv_text(
        "P-1,TXN-10,2025-05-01,10.00,COMPLETED",
        "P-2,TXN-12,2025-05-01,12.00,COMPLETED",
    )

    result = reconcile_texts(core, provider)

    missing_provider = result.details[result.details["result"] == RESULT_MISSING_PROVIDER]
    missing_core = result.details[result.details["result"] == RESULT_MISSING_CORE]
    assert missing_provider["reference"].tolist() == ["TXN-11"]
    assert missing_core["reference"].tolist() == ["TXN-12"]
    assert result.summary["missing_total"] == 2
    assert result.summary["matched"] == 1


def test_duplicate_in_core_is_flagged_not_matched() -> None:
    core = csv_text(
        "C-1,TXN-20,2025-05-01,20.00,COMPLETED",
        "C-2,TXN-20,2025-05-01,20.00,COMPLETED",
    )
    provider = csv_text("P-1,TXN-20,2025-05-01,20.00,COMPLETED")

    result = reconcile_texts(core, provider)
    row = result.details.iloc[0]

    assert row["result"] == RESULT_DUP_CORE
    assert int(row["core_count"]) == 2
    assert int(row["provider_count"]) == 1
    assert "C-1; C-2" == row["core_transaction_id"]
    assert result.summary["duplicates"] == 1
    assert result.summary["duplicate_extra_records"] == 1
    assert result.summary["matched"] == 0


def test_duplicate_in_provider_is_flagged() -> None:
    core = csv_text("C-1,TXN-21,2025-05-01,21.00,COMPLETED")
    provider = csv_text(
        "P-1,TXN-21,2025-05-01,21.00,COMPLETED",
        "P-2,TXN-21,2025-05-01,21.00,COMPLETED",
    )

    result = reconcile_texts(core, provider)

    assert result.details.iloc[0]["result"] == RESULT_DUP_PROVIDER
    assert result.summary["duplicates"] == 1


def test_duplicate_in_both_sources_is_flagged() -> None:
    core = csv_text(
        "C-1,TXN-22,2025-05-01,22.00,COMPLETED",
        "C-2,TXN-22,2025-05-01,22.00,COMPLETED",
    )
    provider = csv_text(
        "P-1,TXN-22,2025-05-01,22.00,COMPLETED",
        "P-2,TXN-22,2025-05-01,22.00,COMPLETED",
    )

    result = reconcile_texts(core, provider)

    assert result.details.iloc[0]["result"] == "Duplicate in both"
    assert result.summary["duplicate_extra_records"] == 2


def test_aliases_and_formatted_amounts_are_supported() -> None:
    core_csv = (
        "id,transaction_reference,transaction_amount,posted_date,transaction_status\n"
        'C-1,TXN-30,"$1,234.50",2025-05-01,completed\n'
    )
    provider_csv = (
        "id,transaction_reference,transaction_amount,posted_date,transaction_status\n"
        'P-1,TXN-30,"USD 1,234.50",2025-05-01,COMPLETED\n'
    )

    result = reconcile_texts(core_csv, provider_csv)

    assert result.details.iloc[0]["result"] == RESULT_MATCHED
    assert result.core.iloc[0]["amount"] == pytest.approx(1234.50)
    assert result.core.iloc[0]["amount_cents"] == 123450
    assert result.core.iloc[0]["transaction_id"] == "C-1"


def test_missing_required_columns_raises_clear_error() -> None:
    bad_csv = "reference,amount\nTXN-1,10.00\n"

    with pytest.raises(CSVValidationError) as exc_info:
        reconcile_texts(bad_csv, csv_text("P-1,TXN-1,2025-05-01,10.00,COMPLETED"))

    error = exc_info.value
    assert set(error.missing_columns) == {"transaction_date", "status"}
    assert "missing required column" in str(error)
    assert "transaction_date" in str(error)
    assert "status" in str(error)


def test_invalid_amount_and_date_report_row_issues() -> None:
    bad_core = csv_text(
        "C-1,TXN-40,not-a-date,10.00,COMPLETED",
        "C-2,TXN-41,2025-05-01,not-money,COMPLETED",
    )
    provider = csv_text(
        "P-1,TXN-40,2025-05-01,10.00,COMPLETED",
        "P-2,TXN-41,2025-05-01,10.00,COMPLETED",
    )

    with pytest.raises(CSVValidationError) as exc_info:
        reconcile_texts(bad_core, provider)

    issues = exc_info.value.row_issues
    assert len(issues) == 2
    assert {issue.column for issue in issues} == {"transaction_date", "amount"}
    assert {issue.row_number for issue in issues} == {2, 3}


def test_empty_and_unreadable_csv_files_fail_gracefully() -> None:
    with pytest.raises(CSVValidationError, match="empty"):
        load_transactions(io.StringIO(""), "Core banking file")

    with pytest.raises(CSVValidationError, match="UTF-8 CSV"):
        load_transactions(b"\xff\xfe\x00\x00not valid", "Payment provider file")


def test_sqlite_round_trip(tmp_path: Path) -> None:
    result = reconcile_files(SAMPLE_CORE, SAMPLE_PROVIDER)
    db_path = tmp_path / "history.db"

    run_id = save_reconciliation(result, db_path)
    runs = list_runs(db_path=db_path)
    saved = get_run(run_id, db_path)

    assert run_id == 1
    assert len(runs) == 1
    assert int(runs.iloc[0]["matched"]) == 7
    assert int(runs.iloc[0]["discrepancies"]) == 7
    assert saved is not None
    assert saved.summary["amount_mismatches"] == 1
    assert len(saved.details) == 14
    assert saved.details["reference"].tolist() == result.details["reference"].tolist()
    assert (
        saved.details[saved.details["result"] == RESULT_MISMATCHED].iloc[0]["reference"]
        == "TXN-1045"
    )


def test_csv_export_contains_detail_rows_and_discrepancy_filter() -> None:
    result = reconcile_files(SAMPLE_CORE, SAMPLE_PROVIDER)

    full = build_csv_report(result)
    discrepancies = build_csv_report(result, discrepancies_only=True)

    assert full.startswith(b"\xef\xbb\xbf")
    full_text = full.decode("utf-8-sig")
    discrepancy_text = discrepancies.decode("utf-8-sig")
    assert "Result,Reference,Core transaction ID" in full_text
    assert "TXN-1042" in full_text
    assert full_text.count("\n") == 15
    assert discrepancy_text.count("\n") == 8
    assert "TXN-1042" not in discrepancy_text
    assert "TXN-1045" in discrepancy_text


def test_excel_export_has_expected_sheets_and_highlights() -> None:
    result = reconcile_files(SAMPLE_CORE, SAMPLE_PROVIDER)
    workbook = load_workbook(io.BytesIO(build_excel_report(result)))

    assert workbook.sheetnames == [
        "Summary",
        "Reconciliation",
        "Discrepancies",
        "Matched",
        "Core Banking",
        "Payment Provider",
    ]
    assert workbook["Summary"]["A9"].value == "Total transactions"
    assert workbook["Summary"]["B9"].value == 28
    assert workbook["Discrepancies"].max_row == 8
    assert workbook["Core Banking"].max_row == 15

    sheet = workbook["Discrepancies"]
    headers = [cell.value for cell in sheet[1]]
    reference_column = headers.index("Reference") + 1
    amount_column = headers.index("Core amount") + 1
    target_row = next(
        row
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row=row, column=reference_column).value == "TXN-1045"
    )
    assert sheet.cell(row=target_row, column=amount_column).fill.fgColor.rgb.endswith(
        "FECACA"
    )


def test_csv_export_neutralises_formula_injection() -> None:
    core = csv_text("C-1,=HYPERLINK(\"http://example.test\"),2025-05-01,10.00,COMPLETED")
    provider = csv_text(
        "P-1,=HYPERLINK(\"http://example.test\"),2025-05-01,10.00,COMPLETED"
    )
    result = reconcile_texts(core, provider)

    report = build_csv_report(result).decode("utf-8-sig")

    assert "'=HYPERLINK" in report


def test_result_frames_are_not_mutated_by_reconciliation() -> None:
    core = load_transactions(
        io.StringIO(csv_text("C-1,TXN-50,2025-05-01,50.00,COMPLETED")),
        "Core banking file",
    )
    provider = load_transactions(
        io.StringIO(csv_text("P-1,TXN-50,2025-05-01,50.00,COMPLETED")),
        "Payment provider file",
    )
    core_before = core.copy(deep=True)

    reconcile_transactions(core, provider)

    pd.testing.assert_frame_equal(core, core_before)
