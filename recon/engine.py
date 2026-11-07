"""Core reconciliation engine.

The engine accepts two CSV sources, validates and normalises them, then compares
transactions by their shared ``reference`` value.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pandas as pd

# Result labels are also used in the UI and exported reports.
RESULT_MATCHED = "Matched"
RESULT_MISMATCHED = "Mismatched"
RESULT_MISSING_CORE = "Missing in core"
RESULT_MISSING_PROVIDER = "Missing in provider"
RESULT_DUP_BOTH = "Duplicate in both"
RESULT_DUP_CORE = "Duplicate in core"
RESULT_DUP_PROVIDER = "Duplicate in provider"

RESULT_PRIORITY = {
    RESULT_MISMATCHED: 0,
    RESULT_MISSING_PROVIDER: 1,
    RESULT_MISSING_CORE: 2,
    RESULT_DUP_BOTH: 3,
    RESULT_DUP_CORE: 4,
    RESULT_DUP_PROVIDER: 5,
    RESULT_MATCHED: 6,
}

DETAIL_COLUMNS = [
    "result",
    "reference",
    "core_transaction_id",
    "provider_transaction_id",
    "core_amount",
    "provider_amount",
    "amount_difference",
    "core_date",
    "provider_date",
    "core_status",
    "provider_status",
    "core_currency",
    "provider_currency",
    "core_customer",
    "provider_customer",
    "core_count",
    "provider_count",
    "mismatch_fields",
    "note",
]

REFERENCE_ALIASES = {
    "reference",
    "transaction_reference",
    "transaction_ref",
    "txn_reference",
    "txn_ref",
    "reference_id",
    "ref_id",
    "reference_number",
    "payment_reference",
}
AMOUNT_ALIASES = {
    "amount",
    "transaction_amount",
    "txn_amount",
    "gross_amount",
    "net_amount",
    "payment_amount",
}
DATE_ALIASES = {
    "transaction_date",
    "date",
    "txn_date",
    "posted_date",
    "posting_date",
    "value_date",
    "created_at",
    "transaction_timestamp",
    "timestamp",
}
STATUS_ALIASES = {
    "status",
    "transaction_status",
    "txn_status",
    "payment_status",
    "state",
}
OPTIONAL_ALIASES = {
    "transaction_id": {
        "transaction_id",
        "id",
        "txn_id",
        "core_transaction_id",
        "provider_transaction_id",
        "bank_transaction_id",
        "payment_id",
    },
    "customer_name": {
        "customer_name",
        "customer",
        "payer_name",
        "account_name",
        "cardholder_name",
    },
    "description": {
        "description",
        "narration",
        "memo",
        "note",
        "notes",
        "details",
    },
    "payment_method": {
        "payment_method",
        "method",
        "channel",
        "payment_channel",
        "instrument",
    },
    "currency": {"currency", "ccy", "currency_code"},
}

REQUIRED_CANONICAL = {
    "reference": REFERENCE_ALIASES,
    "amount": AMOUNT_ALIASES,
    "transaction_date": DATE_ALIASES,
    "status": STATUS_ALIASES,
}

CURRENCY_SYMBOLS = "$€£¥₹₽₩₪₫฿"


@dataclass(frozen=True)
class RowIssue:
    """A single invalid value found while validating a source file."""

    row_number: int
    column: str
    message: str


class CSVValidationError(ValueError):
    """Raised when a source CSV cannot be safely reconciled."""

    def __init__(
        self,
        message: str,
        *,
        missing_columns: list[str] | None = None,
        row_issues: list[RowIssue] | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_columns = missing_columns or []
        self.row_issues = row_issues or []


@dataclass
class ReconciliationResult:
    """Reconciliation artefacts for one pair of source files."""

    details: pd.DataFrame
    core: pd.DataFrame
    provider: pd.DataFrame
    summary: dict[str, Any]
    core_filename: str
    provider_filename: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def discrepancies(self) -> pd.DataFrame:
        return self.details[self.details["result"] != RESULT_MATCHED].copy()

    @property
    def matched(self) -> pd.DataFrame:
        return self.details[self.details["result"] == RESULT_MATCHED].copy()

    @property
    def discrepancy_types(self) -> list[str]:
        present = set(self.discrepancies["result"].tolist())
        return [result for result in RESULT_PRIORITY if result in present]


def _normalise_header(column: object) -> str:
    text = str(column).replace("\ufeff", "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _normalise_status(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _display_filename(source: object, fallback: str) -> str:
    name = getattr(source, "name", None)
    if name:
        return Path(str(name)).name
    if isinstance(source, (str, Path)):
        return Path(source).name
    return fallback


def _read_csv_bytes(source: bytes, label: str) -> pd.DataFrame:
    if not source.strip():
        raise CSVValidationError(f"{label} is empty.")
    return pd.read_csv(io.BytesIO(source), dtype=str, keep_default_na=False)


def _read_csv_source(source: object, label: str) -> pd.DataFrame:
    """Read a CSV from an upload, bytes object, or path with friendly errors."""

    if isinstance(source, bytes):
        return _read_csv_bytes(source, label)

    if hasattr(source, "read"):
        data = source.read()  # type: ignore[union-attr]
        if isinstance(data, bytes):
            return _read_csv_bytes(data, label)
        if isinstance(data, str):
            if not data.strip():
                raise CSVValidationError(f"{label} is empty.")
            return pd.read_csv(io.StringIO(data), dtype=str, keep_default_na=False)
        raise CSVValidationError(f"{label} could not be read as a CSV file.")

    path = Path(str(source))
    if not path.exists():
        raise CSVValidationError(f"{label} could not be found: {path.name}")
    if not path.is_file():
        raise CSVValidationError(f"{label} is not a file: {path.name}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _parse_amount_to_cents(value: object) -> int:
    """Parse common money formats into integer cents without float drift."""

    text = str(value).strip()
    if not text:
        raise ValueError("amount is blank")

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    # Allow a leading/trailing ISO currency code, e.g. "USD 25.00".
    text = re.sub(r"^[A-Za-z]{3}\s+", "", text)
    text = re.sub(r"\s+[A-Za-z]{3}$", "", text)
    for symbol in CURRENCY_SYMBOLS:
        text = text.replace(symbol, "")
    text = text.replace(" ", "")

    if not re.fullmatch(r"[+-]?\d[\d,.]*", text):
        raise ValueError(f"invalid amount {str(value).strip()!r}")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = ".".join(parts)
        else:
            text = text.replace(",", "")

    if text.count(".") > 1:
        raise ValueError(f"invalid amount {str(value).strip()!r}")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount {str(value).strip()!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"invalid amount {str(value).strip()!r}")
    if negative:
        amount = -abs(amount)

    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(rounded * 100)


def _map_columns(
    frame: pd.DataFrame, label: str, filename: str
) -> tuple[pd.DataFrame, list[str]]:
    normalised_headers = [_normalise_header(column) for column in frame.columns]
    rename_map: dict[object, str] = {}
    missing: list[str] = []

    for canonical, aliases in REQUIRED_CANONICAL.items():
        match_index = next(
            (index for index, header in enumerate(normalised_headers) if header in aliases),
            None,
        )
        if match_index is None:
            missing.append(canonical)
        else:
            rename_map[frame.columns[match_index]] = canonical

    if missing:
        expected = ", ".join(REQUIRED_CANONICAL)
        raise CSVValidationError(
            f"{label} ({filename}) is missing required column(s): {', '.join(missing)}. "
            f"Expected columns are: {expected}.",
            missing_columns=missing,
        )

    for canonical, aliases in OPTIONAL_ALIASES.items():
        match_index = next(
            (index for index, header in enumerate(normalised_headers) if header in aliases),
            None,
        )
        if match_index is not None:
            rename_map[frame.columns[match_index]] = canonical

    mapped = frame.rename(columns=rename_map).copy()
    return mapped, sorted(rename_map.values())


def load_transactions(
    source: object,
    label: str = "Transaction file",
    *,
    filename: str | None = None,
) -> pd.DataFrame:
    """Load, validate, and normalise one transaction CSV.

    Args:
        source: A Streamlit upload, path, bytes, or text/binary file-like object.
        label: Human-readable source name used in validation errors.
        filename: Optional display filename for byte streams or uploads.

    Returns:
        A normalised DataFrame with parsed amounts, ISO dates, and source row numbers.

    Raises:
        CSVValidationError: For unreadable files, missing columns, or invalid values.
    """

    resolved_filename = filename or _display_filename(source, "uploaded CSV")
    display_name = f"{label} ({resolved_filename})"
    try:
        frame = _read_csv_source(source, display_name)
    except CSVValidationError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise CSVValidationError(f"{display_name} is empty.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError, OSError) as exc:
        raise CSVValidationError(
            f"{display_name} could not be read as a UTF-8 CSV file. "
            "Check the delimiter and file encoding."
        ) from exc

    if frame.empty or len(frame.columns) == 0:
        raise CSVValidationError(f"{display_name} contains no transaction rows.")

    frame, _ = _map_columns(frame, label, resolved_filename)

    # Keep all populated values as trimmed strings; empty strings become NA below.
    for column in frame.columns:
        frame[column] = frame[column].map(
            lambda value: value.strip() if isinstance(value, str) else value
        )

    row_issues: list[RowIssue] = []
    amount_cents: list[int | None] = []
    normalised_dates: list[str | None] = []
    status_keys: list[str] = []
    references: list[str] = []

    raw_dates = frame["transaction_date"].astype("string")
    try:
        parsed_dates = pd.to_datetime(
            raw_dates, errors="coerce", format="mixed", utc=True
        )
        parsed_date_strings = parsed_dates.dt.strftime("%Y-%m-%d").tolist()
    except (TypeError, ValueError):
        parsed_date_strings = [None] * len(frame)

    for index, row in frame.iterrows():
        row_number = int(index) + 2  # +2 accounts for header row and 0-based index

        reference = str(row.get("reference", "")).strip()
        references.append(reference)
        if not reference:
            row_issues.append(RowIssue(row_number, "reference", "reference is blank"))

        try:
            amount_cents.append(_parse_amount_to_cents(row.get("amount", "")))
        except ValueError as exc:
            amount_cents.append(None)
            row_issues.append(RowIssue(row_number, "amount", str(exc)))

        date_value = parsed_date_strings[int(index)]
        if not date_value or pd.isna(date_value):
            normalised_dates.append(None)
            row_issues.append(
                RowIssue(row_number, "transaction_date", "date could not be parsed")
            )
        else:
            normalised_dates.append(str(date_value))

        status = str(row.get("status", "")).strip()
        status_keys.append(_normalise_status(status))
        if not status:
            row_issues.append(RowIssue(row_number, "status", "status is blank"))

    if row_issues:
        preview = "; ".join(
            f"row {issue.row_number} ({issue.column}): {issue.message}"
            for issue in row_issues[:4]
        )
        extra = len(row_issues) - 4
        if extra > 0:
            preview += f"; and {extra} more"
        raise CSVValidationError(
            f"{display_name} has {len(row_issues)} invalid value(s): {preview}.",
            row_issues=row_issues,
        )

    frame["reference"] = references
    frame["amount_cents"] = amount_cents
    frame["amount"] = [cents / 100 for cents in amount_cents]
    frame["transaction_date"] = normalised_dates
    frame["status"] = frame["status"].astype(str).str.strip()
    frame["status_key"] = status_keys
    frame["source_row"] = [int(index) + 2 for index in frame.index]

    for optional in ("transaction_id", "customer_name", "description", "payment_method", "currency"):
        if optional not in frame.columns:
            frame[optional] = ""

    return frame.reset_index(drop=True)


def _join_unique(values: pd.Series) -> str | None:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return None
    return "; ".join(dict.fromkeys(cleaned))


def _first_value(group: pd.DataFrame | None, column: str) -> Any:
    if group is None or group.empty:
        return None
    value = group.iloc[0].get(column)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def _build_note(
    result: str,
    mismatch_fields: list[str],
    core_count: int,
    provider_count: int,
) -> str:
    if result == RESULT_MATCHED:
        return "Amount, date, and status match."
    if result == RESULT_MISSING_PROVIDER:
        return "Reference is present in core banking but not in the payment provider file."
    if result == RESULT_MISSING_CORE:
        return "Reference is present in the payment provider but not in core banking."
    if result.startswith("Duplicate"):
        parts = []
        if core_count > 1:
            parts.append(f"{core_count} core records")
        if provider_count > 1:
            parts.append(f"{provider_count} provider records")
        detail = " and ".join(parts) if parts else "multiple records"
        return f"Reference appears as {detail}; review before matching."
    if result == RESULT_MISMATCHED:
        return f"Fields do not agree: {', '.join(mismatch_fields)}."
    return ""


def reconcile_transactions(
    core: pd.DataFrame,
    provider: pd.DataFrame,
    *,
    core_filename: str = "core_banking.csv",
    provider_filename: str = "payment_provider.csv",
) -> ReconciliationResult:
    """Compare normalised core-banking and payment-provider frames by reference."""

    required = {"reference", "amount_cents", "transaction_date", "status_key"}
    for name, frame in (("core", core), ("provider", provider)):
        if not required.issubset(frame.columns):
            raise ValueError(
                f"The {name} frame is not normalised. Use load_transactions() first."
            )

    core_groups = {reference: group for reference, group in core.groupby("reference")}
    provider_groups = {
        reference: group for reference, group in provider.groupby("reference")
    }
    references = sorted(set(core_groups) | set(provider_groups))

    records: list[dict[str, Any]] = []
    for reference in references:
        core_group = core_groups.get(reference)
        provider_group = provider_groups.get(reference)
        core_count = 0 if core_group is None else int(len(core_group))
        provider_count = 0 if provider_group is None else int(len(provider_group))

        core_amount_cents = _first_value(core_group, "amount_cents")
        provider_amount_cents = _first_value(provider_group, "amount_cents")
        core_amount = (
            None if core_amount_cents is None else round(float(core_amount_cents) / 100, 2)
        )
        provider_amount = (
            None
            if provider_amount_cents is None
            else round(float(provider_amount_cents) / 100, 2)
        )
        amount_difference = (
            None
            if core_amount is None or provider_amount is None
            else round(provider_amount - core_amount, 2)
        )

        mismatch_fields: list[str] = []
        if core_count > 1 or provider_count > 1:
            if core_count > 1 and provider_count > 1:
                result = RESULT_DUP_BOTH
            elif core_count > 1:
                result = RESULT_DUP_CORE
            else:
                result = RESULT_DUP_PROVIDER
        elif core_count == 0:
            result = RESULT_MISSING_CORE
        elif provider_count == 0:
            result = RESULT_MISSING_PROVIDER
        else:
            if core_amount_cents != provider_amount_cents:
                mismatch_fields.append("Amount")
            if _first_value(core_group, "transaction_date") != _first_value(
                provider_group, "transaction_date"
            ):
                mismatch_fields.append("Date")
            if _first_value(core_group, "status_key") != _first_value(
                provider_group, "status_key"
            ):
                mismatch_fields.append("Status")
            result = RESULT_MISMATCHED if mismatch_fields else RESULT_MATCHED

        note = _build_note(result, mismatch_fields, core_count, provider_count)
        if result.startswith("Duplicate"):
            if core_count == 0:
                note += " No core record was found."
            if provider_count == 0:
                note += " No payment-provider record was found."

        records.append(
            {
                "result": result,
                "reference": reference,
                "core_transaction_id": _join_unique(
                    core_group["transaction_id"] if core_group is not None else pd.Series(dtype=str)
                ),
                "provider_transaction_id": _join_unique(
                    provider_group["transaction_id"]
                    if provider_group is not None
                    else pd.Series(dtype=str)
                ),
                "core_amount": core_amount,
                "provider_amount": provider_amount,
                "amount_difference": amount_difference,
                "core_date": _first_value(core_group, "transaction_date"),
                "provider_date": _first_value(provider_group, "transaction_date"),
                "core_status": _first_value(core_group, "status"),
                "provider_status": _first_value(provider_group, "status"),
                "core_currency": _first_value(core_group, "currency"),
                "provider_currency": _first_value(provider_group, "currency"),
                "core_customer": _first_value(core_group, "customer_name"),
                "provider_customer": _first_value(provider_group, "customer_name"),
                "core_count": core_count,
                "provider_count": provider_count,
                "mismatch_fields": ", ".join(mismatch_fields) or None,
                "note": note,
            }
        )

    details = pd.DataFrame(records, columns=DETAIL_COLUMNS)
    details["_priority"] = details["result"].map(RESULT_PRIORITY).fillna(99).astype(int)
    details = (
        details.sort_values(["_priority", "reference"], kind="stable")
        .drop(columns="_priority")
        .reset_index(drop=True)
    )

    matched_count = int((details["result"] == RESULT_MATCHED).sum())
    amount_mismatches = int(
        details["mismatch_fields"].fillna("").str.contains("Amount", regex=False).sum()
    )
    date_mismatches = int(
        details["mismatch_fields"].fillna("").str.contains("Date", regex=False).sum()
    )
    status_mismatches = int(
        details["mismatch_fields"].fillna("").str.contains("Status", regex=False).sum()
    )
    missing_core = int((details["result"] == RESULT_MISSING_CORE).sum())
    missing_provider = int((details["result"] == RESULT_MISSING_PROVIDER).sum())
    duplicate_mask = details["result"].str.startswith("Duplicate")
    duplicates = int(duplicate_mask.sum())
    duplicate_extra_records = int(
        sum(
            max(0, int(row.core_count) - 1) + max(0, int(row.provider_count) - 1)
            for row in details.loc[duplicate_mask].itertuples()
        )
    )
    total_transactions = int(len(core) + len(provider))
    unique_references = int(len(details))
    discrepancy_count = unique_references - matched_count

    summary = {
        "total_transactions": total_transactions,
        "core_transactions": int(len(core)),
        "provider_transactions": int(len(provider)),
        "unique_references": unique_references,
        "matched": matched_count,
        "mismatched": int((details["result"] == RESULT_MISMATCHED).sum()),
        "missing_in_core": missing_core,
        "missing_in_provider": missing_provider,
        "missing_total": missing_core + missing_provider,
        "duplicates": duplicates,
        "duplicate_extra_records": duplicate_extra_records,
        "amount_mismatches": amount_mismatches,
        "date_mismatches": date_mismatches,
        "status_mismatches": status_mismatches,
        "discrepancies": discrepancy_count,
        "match_rate": round(matched_count / unique_references * 100, 1)
        if unique_references
        else 0.0,
    }

    return ReconciliationResult(
        details=details,
        core=core,
        provider=provider,
        summary=summary,
        core_filename=core_filename,
        provider_filename=provider_filename,
    )


def reconcile_files(
    core_source: object,
    provider_source: object,
    *,
    core_filename: str | None = None,
    provider_filename: str | None = None,
) -> ReconciliationResult:
    """Load both sources and reconcile them in one call."""

    core_name = core_filename or _display_filename(core_source, "core_banking.csv")
    provider_name = provider_filename or _display_filename(
        provider_source, "payment_provider.csv"
    )
    core = load_transactions(
        core_source, "Core banking file", filename=core_name
    )
    provider = load_transactions(
        provider_source, "Payment provider file", filename=provider_name
    )
    return reconcile_transactions(
        core,
        provider,
        core_filename=core_name,
        provider_filename=provider_name,
    )
