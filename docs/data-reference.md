# Data Reference

This page defines every data contract used by LedgerMatch: input CSVs, normalized source frames, reconciliation results, summary fields, SQLite tables, and export formats.

## Input files

### Required logical columns

| Logical field | Required | Used for |
|---|---|---|
| `reference` | Yes | Matching key |
| `amount` | Yes | Amount comparison |
| `transaction_date` | Yes | Calendar-date comparison |
| `status` | Yes | Status comparison |

### Optional recognized columns

| Logical field | Required | Used for |
|---|---|---|
| `transaction_id` | No | Display and joined IDs for duplicate groups |
| `customer_name` | No | Search and report context |
| `description` | No | Source-record display |
| `payment_method` | No | Source-record display |
| `currency` | No | Reporting context only; not converted or compared |

Unrecognized columns are ignored. They do not appear in normalized source frames or exports.

### Accepted column aliases

Header matching is case-insensitive and punctuation-insensitive. The first alias found becomes the canonical column.

#### `reference`

```text
reference
transaction_reference
transaction_ref
txn_reference
txn_ref
reference_id
ref_id
reference_number
payment_reference
```

#### `amount`

```text
amount
transaction_amount
txn_amount
gross_amount
net_amount
payment_amount
```

#### `transaction_date`

```text
transaction_date
date
txn_date
posted_date
posting_date
value_date
created_at
transaction_timestamp
timestamp
```

#### `status`

```text
status
transaction_status
txn_status
payment_status
state
```

#### `transaction_id`

```text
transaction_id
id
txn_id
core_transaction_id
provider_transaction_id
bank_transaction_id
payment_id
```

#### `customer_name`

```text
customer_name
customer
payer_name
account_name
cardholder_name
```

#### `description`

```text
description
narration
memo
note
notes
details
```

#### `payment_method`

```text
payment_method
method
channel
payment_channel
instrument
```

#### `currency`

```text
currency
ccy
currency_code
```

### Example input

```csv
transaction_id,reference,transaction_date,amount,currency,status,customer_name,description,payment_method
CB-20250501-001,TXN-1042,2025-05-01,250.00,USD,COMPLETED,Acme Retail,Invoice INV-2041 payment,ACH
```

Both files need the same four logical required columns, but their headers and optional extra columns can differ.

### Reference format

- Compared exactly after trimming leading/trailing whitespace.
- Case-sensitive (`TXN-1` and `txn-1` are different references).
- Blank references are invalid.
- References should be unique per source in the ideal case; duplicates are detected explicitly.

### Amount input formats

| Input form | Supported |
|---|---|
| `250.00` | Yes |
| `1,234.56` | Yes |
| `$1,234.56` | Yes |
| `€1.234,56` | Yes, separator inference |
| `USD 1,234.56` | Yes |
| `(25.00)` | Yes, negative |
| `-25.00` | Yes |
| `+25.00` | Yes |
| `1 234.56` | Yes, spaces removed |
| `not-money` | No — validation error |
| Blank | No — validation error |

Amounts are quantized to two decimal places with `ROUND_HALF_UP`. Currencies with zero or three minor units require customization.

### Date input behavior

- Parsed with Pandas mixed-format inference and UTC normalization.
- Stored and compared as `YYYY-MM-DD`.
- Time-of-day and timezone offset differences can be folded into the compared calendar date.
- Unparseable values are rejected.

For production imports, normalize ambiguous locale formats (for example, `05/06/2025`) upstream to ISO `YYYY-MM-DD`.

### Status input behavior

- Trimmed.
- Internal whitespace collapsed.
- Uppercased for the comparison key.
- Original trimmed display value retained.
- No semantic aliases (for example, `SUCCESS` is not treated as `COMPLETED`).

## Normalized source frame

`load_transactions()` returns a Pandas DataFrame with this schema. Both source frames use the same normalized columns.

| Column | Type | Description |
|---|---|---|
| `transaction_id` | string | Source transaction identifier; blank if absent |
| `reference` | string | Trimmed matching reference |
| `transaction_date` | string | ISO `YYYY-MM-DD` date used for comparison |
| `amount` | float | Amount in major currency units for display |
| `currency` | string | Optional currency code or label |
| `status` | string | Trimmed source status for display |
| `customer_name` | string | Optional customer name |
| `description` | string | Optional description/narration |
| `payment_method` | string | Optional payment method/channel |
| `amount_cents` | int64 | Exact amount used for comparison |
| `status_key` | string | Normalized status used for comparison |
| `source_row` | int64 | CSV row number, with header = 1 |

Notes:

- The DataFrame index is reset to a 0-based range.
- Empty optional values are represented as empty strings.
- Empty required values cause a `CSVValidationError` before the DataFrame is returned.
- `amount_cents` and `status_key` are internal comparison fields; they are not included in human-facing Excel source sheets.
- `source_row` allows an operator to locate the original CSV row.

## Reconciliation detail frame

`ReconciliationResult.details` is a DataFrame with one row per reference and these columns, in canonical order:

| Column | Type | Description |
|---|---|---|
| `result` | string | `Matched`, `Mismatched`, `Missing in core`, `Missing in provider`, `Duplicate in core`, `Duplicate in provider`, or `Duplicate in both` |
| `reference` | string | Shared reference |
| `core_transaction_id` | string / null | Core transaction ID(s), joined with `; ` when duplicates |
| `provider_transaction_id` | string / null | Provider transaction ID(s), joined with `; ` when duplicates |
| `core_amount` | float / null | Core amount in major units; first row of a duplicate group |
| `provider_amount` | float / null | Provider amount in major units; first row of a duplicate group |
| `amount_difference` | float / null | Provider minus core, when both sides exist |
| `core_date` | string / null | ISO core date |
| `provider_date` | string / null | ISO provider date |
| `core_status` | string / null | Core display status |
| `provider_status` | string / null | Provider display status |
| `core_currency` | string / null | Core currency |
| `provider_currency` | string / null | Provider currency |
| `core_customer` | string / null | Core customer name |
| `provider_customer` | string / null | Provider customer name |
| `core_count` | int | Number of core rows with the reference |
| `provider_count` | int | Number of provider rows with the reference |
| `mismatch_fields` | string / null | Comma-separated `Amount`, `Date`, `Status` fields that differ |
| `note` | string | Human-readable classification/review note |

### Result labels

| Label | Meaning |
|---|---|
| `Matched` | Exactly one row per source; amount, date, and status agree |
| `Mismatched` | Exactly one row per source; at least one field differs |
| `Missing in core` | Reference is only in provider |
| `Missing in provider` | Reference is only in core |
| `Duplicate in core` | More than one core row; provider count is not greater than one |
| `Duplicate in provider` | More than one provider row; core count is not greater than one |
| `Duplicate in both` | More than one row in both sources |

### Result sorting

Detail rows are sorted by severity and then reference:

```text
Mismatched
Missing in provider
Missing in core
Duplicate in both
Duplicate in core
Duplicate in provider
Matched
```

## Summary object

`ReconciliationResult.summary` is a dictionary:

| Key | Type | Description |
|---|---|---|
| `total_transactions` | int | Raw core rows + raw provider rows |
| `core_transactions` | int | Raw core row count |
| `provider_transactions` | int | Raw provider row count |
| `unique_references` | int | Reference-level result count |
| `matched` | int | Exact matches |
| `mismatched` | int | References with field disagreement |
| `missing_in_core` | int | Missing from core |
| `missing_in_provider` | int | Missing from provider |
| `missing_total` | int | Missing in core + missing in provider |
| `duplicates` | int | Duplicate reference cases |
| `duplicate_extra_records` | int | Extra rows beyond the first across duplicate groups |
| `amount_mismatches` | int | Mismatches involving amount |
| `date_mismatches` | int | Mismatches involving date |
| `status_mismatches` | int | Mismatches involving status |
| `discrepancies` | int | Unique references minus exact matches |
| `match_rate` | float | Exact matches divided by unique references, percent, one decimal |

### Formula summary

```text
total_transactions = len(core) + len(provider)
unique_references  = matched + mismatched + missing_in_core
                     + missing_in_provider + duplicates
discrepancies      = unique_references - matched
match_rate         = matched / unique_references * 100
```

`duplicate_extra_records` is calculated as:

```text
sum(max(0, core_count - 1) + max(0, provider_count - 1))
```

over duplicate reference cases.

Field mismatch counts can overlap: one mismatched reference can count in amount, date, and status simultaneously.

## ReconciliationResult object

```python
@dataclass
class ReconciliationResult:
    details: pd.DataFrame
    core: pd.DataFrame
    provider: pd.DataFrame
    summary: dict
    core_filename: str
    provider_filename: str
    generated_at: datetime
```

Properties:

| Property | Returns |
|---|---|
| `discrepancies` | Copy of detail rows where result is not `Matched` |
| `matched` | Copy of detail rows where result is `Matched` |
| `discrepancy_types` | Present discrepancy labels in canonical severity order |

`generated_at` is timezone-aware UTC.

## Validation objects

### `CSVValidationError`

Raised for unreadable files, empty files, missing columns, or invalid rows.

Attributes:

| Attribute | Type | Meaning |
|---|---|---|
| `missing_columns` | `list[str]` | Canonical required columns that were missing |
| `row_issues` | `list[RowIssue]` | All invalid values discovered |

The string representation is suitable for display to an operator.

### `RowIssue`

```python
@dataclass(frozen=True)
class RowIssue:
    row_number: int
    column: str
    message: str
```

`row_number` is the CSV line number, with the header on line 1.

## SQLite schema

Default path:

```text
data/reconciliation.db
```

Override precedence:

1. Explicit `db_path` argument to a database function.
2. `RECON_DB_PATH` environment variable.
3. `data/reconciliation.db` under the repository root.

### `reconciliation_runs`

```sql
CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    core_filename TEXT NOT NULL,
    provider_filename TEXT NOT NULL,
    core_transactions INTEGER NOT NULL,
    provider_transactions INTEGER NOT NULL,
    total_transactions INTEGER NOT NULL,
    matched INTEGER NOT NULL,
    discrepancies INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
```

`created_at` is an ISO 8601 UTC timestamp. `summary_json` contains the full summary dictionary.

### `reconciliation_results`

```sql
CREATE TABLE IF NOT EXISTS reconciliation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL
        REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    reference TEXT,
    result TEXT,
    core_transaction_id TEXT,
    provider_transaction_id TEXT,
    core_amount REAL,
    provider_amount REAL,
    amount_difference REAL,
    core_date TEXT,
    provider_date TEXT,
    core_status TEXT,
    provider_status TEXT,
    core_currency TEXT,
    provider_currency TEXT,
    core_customer TEXT,
    provider_customer TEXT,
    core_count INTEGER,
    provider_count INTEGER,
    mismatch_fields TEXT,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_run_id
    ON reconciliation_results(run_id);
```

### Persistence boundaries

Stored:

- Run metadata.
- Summary JSON.
- Reference-level detail rows.

Not stored:

- Raw uploaded CSV bytes.
- Unrecognized columns.
- Original file contents.
- A user identity.

The normalized source rows exist only in the current session; to review historical source rows, the original files are needed.

### Useful queries

```sql
-- Recent runs
SELECT id, created_at, matched, discrepancies
FROM reconciliation_runs
ORDER BY id DESC
LIMIT 10;

-- Discrepancies for one run
SELECT reference, result, amount_difference, mismatch_fields, note
FROM reconciliation_results
WHERE run_id = 1 AND result != 'Matched'
ORDER BY id;
```

## Export formats

### File naming

Generated filenames use the run's UTC timestamp:

```text
reconciliation_20251107_193500.xlsx
reconciliation_20251107_193500.csv
reconciliation_discrepancies_20251107_193500.csv
```

### CSV encoding and safety

- Encoding: UTF-8 with BOM (`utf-8-sig`), so Excel recognizes non-ASCII characters.
- Missing values: blank.
- Human-readable headers.
- Text values that begin with `=`, `+`, `-`, or `@` are prefixed with `'` to reduce formula injection risk.
- Full CSV includes all reference-level results.
- Discrepancy CSV includes only rows where `result != "Matched"`.

### CSV column labels

| Internal field | Export label |
|---|---|
| `result` | Result |
| `reference` | Reference |
| `core_transaction_id` | Core transaction ID |
| `provider_transaction_id` | Provider transaction ID |
| `core_amount` | Core amount |
| `provider_amount` | Provider amount |
| `amount_difference` | Difference (provider - core) |
| `core_date` | Core date |
| `provider_date` | Provider date |
| `core_status` | Core status |
| `provider_status` | Provider status |
| `core_currency` | Core currency |
| `provider_currency` | Provider currency |
| `core_customer` | Core customer |
| `provider_customer` | Provider customer |
| `core_count` | Core records |
| `provider_count` | Provider records |
| `mismatch_fields` | Mismatch fields |
| `note` | Review note |

### Excel workbook sheets

| Sheet | Contents |
|---|---|
| `Summary` | Title, generated timestamp, filenames, metrics, result breakdown |
| `Reconciliation` | All reference-level results with highlighting |
| `Discrepancies` | Non-matched rows only |
| `Matched` | Exact matches |
| `Core Banking` | Normalized core records |
| `Payment Provider` | Normalized provider records |

Source sheets use human labels for:

```text
Transaction ID, Reference, Date, Amount, Currency, Status,
Customer, Description, Payment method, CSV row
```

Excel styling includes header fills, frozen headers, autofilters, column widths, amount number formats, and conditional fills for missing/duplicate/mismatched records.

## Related documentation

- [How it works](how-it-works.md)
- [API reference](api-reference.md)
- [Architecture](architecture.md)
