# API Reference

LedgerMatch exposes a small Python API that can be used independently of Streamlit. The engine, persistence layer, and report builders are separate modules.

> **Stability note:** the modules are importable and tested, but the project does not yet declare a semantic-versioning policy for external consumers. Treat function signatures as stable within a release and review changes before upgrading.

## Package exports

```python
from recon import (
    CSVValidationError,
    ReconciliationResult,
    load_transactions,
    reconcile_files,
    reconcile_transactions,
)
```

Additional constants and dataclasses can be imported from their modules:

```python
from recon.engine import RowIssue, DETAIL_COLUMNS, RESULT_MATCHED
from recon.db import SavedRun
```

## Reconciliation engine

### `load_transactions`

```python
def load_transactions(
    source: object,
    label: str = "Transaction file",
    *,
    filename: str | None = None,
) -> pd.DataFrame
```

Reads, maps, validates, and normalizes one transaction CSV.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | object | Bytes, path (`str` / `Path`), or text/binary file-like object |
| `label` | str | Human-readable source name used in error messages |
| `filename` | str or None | Display filename for byte streams or uploads |

**Returns**

A normalized DataFrame with the columns documented in [Data reference](data-reference.md#normalized-source-frame). The DataFrame includes internal `amount_cents`, `status_key`, and `source_row` fields.

**Raises**

- `CSVValidationError` — unreadable/empty file, missing required columns, unparseable dates, invalid amounts, blank references, or blank statuses.
- May propagate unexpected I/O errors that are not wrapped.

**Example**

```python
from pathlib import Path
from recon.engine import load_transactions

core = load_transactions(
    Path("sample_data/core_banking_transactions.csv"),
    label="Core banking file",
)

print(core[["reference", "amount_cents", "transaction_date", "status_key"]].head())
```

### `reconcile_transactions`

```python
def reconcile_transactions(
    core: pd.DataFrame,
    provider: pd.DataFrame,
    *,
    core_filename: str = "core_banking.csv",
    provider_filename: str = "payment_provider.csv",
) -> ReconciliationResult
```

Compares two **normalized** source frames by reference.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `core` | DataFrame | Output of `load_transactions()` for the core source |
| `provider` | DataFrame | Output of `load_transactions()` for the provider source |
| `core_filename` | str | Filename recorded in the result and reports |
| `provider_filename` | str | Filename recorded in the result and reports |

**Required normalized columns**

```text
reference, amount_cents, transaction_date, status_key
```

If these are missing, the function raises `ValueError` with a message directing the caller to use `load_transactions()` first.

**Returns**

A `ReconciliationResult` containing detail rows, normalized source frames, summary metrics, filenames, and generation time.

**Example**

```python
from recon.engine import load_transactions, reconcile_transactions

core = load_transactions("core.csv", "Core banking file")
provider = load_transactions("provider.csv", "Payment provider file")

result = reconcile_transactions(
    core,
    provider,
    core_filename="core.csv",
    provider_filename="provider.csv",
)

print(result.summary)
print(result.discrepancies[["reference", "result", "mismatch_fields"]])
```

### `reconcile_files`

```python
def reconcile_files(
    core_source: object,
    provider_source: object,
    *,
    core_filename: str | None = None,
    provider_filename: str | None = None,
) -> ReconciliationResult
```

Convenience wrapper that loads both sources and reconciles them in one call.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `core_source` | object | Core CSV bytes, path, or file-like object |
| `provider_source` | object | Provider CSV bytes, path, or file-like object |
| `core_filename` | str or None | Explicit display filename for the core source |
| `provider_filename` | str or None | Explicit display filename for the provider source |

**Returns**

`ReconciliationResult`.

**Raises**

`CSVValidationError` for invalid source data.

**Example**

```python
from recon.engine import reconcile_files

result = reconcile_files(
    "sample_data/core_banking_transactions.csv",
    "sample_data/payment_provider_transactions.csv",
)
print(result.summary["matched"], result.summary["discrepancies"])
```

## Result and error types

### `ReconciliationResult`

```python
@dataclass
class ReconciliationResult:
    details: pd.DataFrame
    core: pd.DataFrame
    provider: pd.DataFrame
    summary: dict[str, Any]
    core_filename: str
    provider_filename: str
    generated_at: datetime
```

| Member | Type | Description |
|---|---|---|
| `details` | DataFrame | One row per reference; canonical columns in `DETAIL_COLUMNS` |
| `core` | DataFrame | Normalized core source rows |
| `provider` | DataFrame | Normalized provider source rows |
| `summary` | dict | Counts and match rate documented in [Data reference](data-reference.md#summary-object) |
| `core_filename` | str | Core display name |
| `provider_filename` | str | Provider display name |
| `generated_at` | datetime | UTC generation timestamp |
| `discrepancies` | property → DataFrame | Non-matched detail rows copy |
| `matched` | property → DataFrame | Matched detail rows copy |
| `discrepancy_types` | property → list[str] | Present discrepancy labels in severity order |

`match_rate` is a percentage value from `0.0` to `100.0`, rounded to one decimal.

### `CSVValidationError`

```python
class CSVValidationError(ValueError):
    missing_columns: list[str]
    row_issues: list[RowIssue]
```

Used for all expected source-data validation failures. The string message is intended for direct display.

**Example**

```python
from recon.engine import CSVValidationError, reconcile_files

try:
    result = reconcile_files("core.csv", "provider.csv")
except CSVValidationError as exc:
    print(exc)
    print("Missing:", exc.missing_columns)
    for issue in exc.row_issues:
        print(issue.row_number, issue.column, issue.message)
```

### `RowIssue`

```python
@dataclass(frozen=True)
class RowIssue:
    row_number: int
    column: str
    message: str
```

- `row_number` is the CSV line number.
- `column` is the canonical logical field, not necessarily the original header.

## Constants

The engine exposes labels and ordering constants from `recon.engine`:

```python
RESULT_MATCHED = "Matched"
RESULT_MISMATCHED = "Mismatched"
RESULT_MISSING_CORE = "Missing in core"
RESULT_MISSING_PROVIDER = "Missing in provider"
RESULT_DUP_BOTH = "Duplicate in both"
RESULT_DUP_CORE = "Duplicate in core"
RESULT_DUP_PROVIDER = "Duplicate in provider"

RESULT_PRIORITY = {...}
DETAIL_COLUMNS = [...]
```

Use the constants instead of duplicating display strings in integrations.

## SQLite API

Module: `recon.db`

### `initialize_database`

```python
def initialize_database(db_path: str | Path | None = None) -> Path
```

Creates the database directory and schema if needed. Idempotent.

Returns the resolved database path.

### `save_reconciliation`

```python
def save_reconciliation(
    result: ReconciliationResult,
    db_path: str | Path | None = None,
) -> int
```

Persists a run and all detail rows in one transaction.

Returns the new integer run id.

**Example**

```python
from recon.db import initialize_database, save_reconciliation
from recon.engine import reconcile_files

initialize_database()
result = reconcile_files("core.csv", "provider.csv")
run_id = save_reconciliation(result)
print(f"Saved run {run_id}")
```

### `list_runs`

```python
def list_runs(
    limit: int = 20,
    db_path: str | Path | None = None,
) -> pd.DataFrame
```

Returns recent runs newest-first with columns:

```text
run_id, created_at, core_filename, provider_filename,
total_transactions, matched, discrepancies,
amount_mismatches, missing_total, duplicates
```

`summary_json` is parsed and not returned. The limit is clamped to at least 1.

### `get_run`

```python
def get_run(
    run_id: int,
    db_path: str | Path | None = None,
) -> SavedRun | None
```

Returns a saved run or `None` when the run does not exist.

```python
@dataclass
class SavedRun:
    run_id: int
    created_at: str
    core_filename: str
    provider_filename: str
    summary: dict[str, Any]
    details: pd.DataFrame
```

**Example**

```python
from recon.db import get_run

saved = get_run(1)
if saved:
    print(saved.core_filename, saved.summary["matched"])
    print(saved.details[["reference", "result"]].head())
```

### `format_utc_timestamp`

```python
def format_utc_timestamp(value: str | datetime) -> str
```

Formats an ISO timestamp or datetime for display:

```text
2026-11-07 19:35 UTC
```

Invalid strings are returned unchanged.

### Database path configuration

```python
DEFAULT_DB_PATH  # <repo>/data/reconciliation.db
```

Resolution order:

1. Explicit function argument.
2. `RECON_DB_PATH` environment variable.
3. `DEFAULT_DB_PATH`.

## Report API

Module: `recon.reports`

### `build_csv_report`

```python
def build_csv_report(
    result: ReconciliationResult,
    *,
    discrepancies_only: bool = False,
) -> bytes
```

Builds a human-labeled UTF-8 CSV with BOM.

- `discrepancies_only=False` exports all reference-level rows.
- `discrepancies_only=True` exports only non-matched rows.
- Formula-like text values are neutralized.

**Example**

```python
from recon.reports import build_csv_report

full_csv = build_csv_report(result)
exception_csv = build_csv_report(result, discrepancies_only=True)

with open("reconciliation.csv", "wb") as handle:
    handle.write(full_csv)
```

### `build_excel_report`

```python
def build_excel_report(result: ReconciliationResult) -> bytes
```

Builds a styled multi-sheet `.xlsx` workbook in memory.

Sheets:

```text
Summary
Reconciliation
Discrepancies
Matched
Core Banking
Payment Provider
```

**Example**

```python
from recon.reports import build_excel_report

xlsx = build_excel_report(result)
with open("reconciliation.xlsx", "wb") as handle:
    handle.write(xlsx)
```

## Complete embedding example

```python
from pathlib import Path

from recon.engine import CSVValidationError, reconcile_files
from recon.db import get_run, save_reconciliation
from recon.reports import build_csv_report, build_excel_report

CORE = Path("sample_data/core_banking_transactions.csv")
PROVIDER = Path("sample_data/payment_provider_transactions.csv")

try:
    result = reconcile_files(CORE, PROVIDER)
except CSVValidationError as exc:
    raise SystemExit(f"Invalid input: {exc}") from exc

print("Summary:", result.summary)
print(result.discrepancies[["reference", "result", "mismatch_fields"]])

run_id = save_reconciliation(result)
saved = get_run(run_id)

Path("reports").mkdir(exist_ok=True)
Path("reports/reconciliation.xlsx").write_bytes(build_excel_report(result))
Path("reports/reconciliation.csv").write_bytes(build_csv_report(result))
Path("reports/discrepancies.csv").write_bytes(
    build_csv_report(result, discrepancies_only=True)
)

assert saved is not None
print(f"Stored run {saved.run_id}")
```

## Behavior guarantees and caveats

- `load_transactions()` does not mutate its input.
- `reconcile_transactions()` does not change the source frames.
- Invalid required values cause a complete validation failure; there is no partial-data mode.
- Matching is exact-reference based and case-sensitive after trimming.
- The result is reference-level; duplicate source rows are aggregated into one case.
- Amount comparison is in cents.
- Dates are calendar-day comparisons.
- Statuses are case-insensitive after trimming and whitespace collapse.
- Currency is not compared and no FX conversion is performed.
- Report builders return bytes; persistence to a file, S3, or download stream is the caller's responsibility.
- The SQLite functions are synchronous and open short-lived connections.
- There is no asynchronous API, CLI, or network service in this version.

## Related documentation

- [How it works](how-it-works.md)
- [Data reference](data-reference.md)
- [Implementation guide](implementation-guide.md)
- [Operations](operations.md)
