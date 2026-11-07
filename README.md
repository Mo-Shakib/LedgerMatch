# LedgerMatch — Financial Transaction Reconciliation

A small, local-first reconciliation workspace for comparing a **core banking** transaction export with a **payment provider** export. Built with Python, Pandas, Streamlit, SQLite, and openpyxl.

Upload two CSVs, match records by transaction reference, inspect discrepancies, and download CSV or Excel reports. The app ships with a realistic synthetic demo dataset so it can be evaluated without any real financial data.

## Features

- Clean Streamlit interface with two CSV uploads.
- Exact matching on transaction reference IDs.
- Detection of **matched**, **mismatched**, **missing**, and **duplicate** records.
- Field-level comparison of **amount**, **calendar date**, and **status**.
- Summary metrics for total transactions, exact matches, and discrepancy counts.
- Searchable and filterable discrepancy table.
- Colour highlighting for missing rows, duplicate references, amount mismatches, and date/status mismatches.
- CSV exports for the full result set and discrepancies only.
- Styled multi-sheet Excel report.
- SQLite run history and saved discrepancy snapshots.
- Friendly validation errors for missing columns, invalid values, empty files, and unreadable CSVs.
- Automated tests covering matching logic, ingestion, SQLite persistence, and report output.
- Built-in synthetic sample data with known expected results.

## Quick start

Requires **Python 3.11+** (tested with Python 3.11 and Streamlit 1.67).

```bash
# From the project root
python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
streamlit run app.py
```

Streamlit opens the app at <http://localhost:8501>.

To run it non-interactively on a specific port:

```bash
streamlit run app.py --server.port 8501
```

## Try the built-in demo

1. In the sidebar, select **Built-in sample data**.
2. Click **Run reconciliation**.
3. Explore the discrepancy table, filters, source records, and run history.

The demo is generated from two synthetic files:

- `sample_data/core_banking_transactions.csv`
- `sample_data/payment_provider_transactions.csv`

Expected demo result:

| Metric | Value |
|---|---:|
| Total transactions | 28 |
| Core banking records | 14 |
| Payment provider records | 14 |
| Unique references | 14 |
| Exact matches | 7 |
| Total discrepancy cases | 7 |
| Amount mismatches | 1 |
| Date mismatches | 1 |
| Status mismatches | 1 |
| Missing records | 2 |
| Duplicate references | 2 |
| Exact match rate | 50.0% |

The seeded cases include an amount difference, a one-day date difference, a status difference, one record missing from each source, and a duplicate reference in each source.

To try the upload workflow, choose **Upload CSV files** and upload the two files from `sample_data/`.

## CSV format

Both files need the following logical columns:

```text
reference, amount, transaction_date, status
```

A typical file can include additional context:

```csv
transaction_id,reference,transaction_date,amount,currency,status,customer_name,description,payment_method
CB-20250501-001,TXN-1042,2025-05-01,250.00,USD,COMPLETED,Acme Retail,Invoice INV-2041 payment,ACH
```

### Accepted column aliases

Header matching is case-insensitive and normalises spaces, hyphens, and punctuation.

| Logical field | Common accepted aliases |
|---|---|
| `reference` | `transaction_reference`, `transaction_ref`, `txn_reference`, `reference_id`, `ref_id`, `reference_number`, `payment_reference` |
| `amount` | `transaction_amount`, `txn_amount`, `gross_amount`, `net_amount`, `payment_amount` |
| `transaction_date` | `date`, `txn_date`, `posted_date`, `posting_date`, `value_date`, `created_at`, `timestamp` |
| `status` | `transaction_status`, `txn_status`, `payment_status`, `state` |

Optional display fields: `transaction_id`, `customer_name`, `description`, `payment_method`, and `currency`.

### Amount, date, and status handling

- Amounts are parsed to **integer cents** to avoid floating-point comparison drift.
- Common currency symbols (`$`, `€`, `£`, `¥`, `₹`, and others) and ISO prefixes such as `USD ` are supported.
- Parentheses are treated as negative amounts, e.g. `(25.00)`.
- Dates are normalised to `YYYY-MM-DD`; timestamps are compared by calendar day.
- Statuses are compared case-insensitively after trimming whitespace.
- Empty references, blank statuses, invalid amounts, and unparseable dates are rejected with row-level details rather than silently skipped.

## Matching rules

Transactions are grouped by the exact `reference` value (surrounding whitespace is trimmed; case is preserved).

- **Matched** — the reference occurs exactly once in each source, and amount, date, and status all agree.
- **Mismatched** — both records exist, but one or more compared fields differ.
- **Missing in core** — the reference appears only in the payment provider file.
- **Missing in provider** — the reference appears only in the core banking file.
- **Duplicate in core / provider / both** — the reference occurs more than once in at least one source. Duplicate cases are flagged and are not forced into an arbitrary match.

Each detail row represents one reference. Duplicate groups report record counts and the associated transaction IDs; the **Source records** tab shows every underlying row. The duplicate row displays the first record's amounts, with a review note explaining the duplication.

## Viewing discrepancies

The discrepancy table can be filtered by:

- Reference, transaction ID, customer, status, or review note.
- One or more discrepancy types.
- Amount mismatches only.

Colour legend:

- **Rose row** — missing record.
- **Amber row** — duplicate reference.
- **Red amount cells** — mismatched amount.
- **Yellow date/status cells** — date or status mismatch.

The matched and source-record tabs provide read-only views for audit.

## Downloads

Three downloads are available for every completed run:

1. **Excel workbook (`.xlsx`)** — complete formatted report.
2. **Reconciliation CSV** — all references and comparison fields.
3. **Discrepancies CSV** — only non-exact-match cases.

The Excel workbook contains:

- `Summary` — run metadata and reconciliation metrics.
- `Reconciliation` — all reference-level results with condition highlighting.
- `Discrepancies` — only non-matching cases.
- `Matched` — exact matches.
- `Core Banking` — normalised core source rows.
- `Payment Provider` — normalised provider source rows.

Text values beginning with spreadsheet formula markers are neutralised in exports to reduce CSV/formula injection risk.

## SQLite history

Completed runs are stored in `data/reconciliation.db` by default. The **Run history** tab lists recent runs and lets you inspect a saved snapshot of discrepancies. The database schema and access layer live in `recon/db.py`.

Override the database location:

```bash
RECON_DB_PATH=/path/to/reconciliation.db streamlit run app.py
```

The `data/` directory is created automatically. Database files are excluded by `.gitignore`.

## Tests

```bash
pytest -q
```

The tests cover:

- Demo dataset counts and categories.
- Amount, date, and status comparisons.
- Missing records in both directions.
- Duplicate detection across both sources.
- Column aliases and formatted amounts.
- Missing-column and invalid-row validation.
- Empty and unreadable files.
- SQLite save/list/load round trips.
- CSV and Excel report output, including amount highlighting.
- Protection against formula injection in CSV exports.

## Project structure

```text
.
├── app.py                         # Streamlit interface
├── recon/
│   ├── __init__.py
│   ├── engine.py                  # CSV ingestion, validation, matching
│   ├── db.py                      # SQLite persistence and history
│   └── reports.py                 # CSV and Excel export builders
├── sample_data/
│   ├── core_banking_transactions.csv
│   └── payment_provider_transactions.csv
├── tests/
│   └── test_reconciliation.py
├── .streamlit/config.toml         # Theme
├── requirements.txt
├── pytest.ini
└── README.md
```

## Project notes and limitations

- This is a **local, single-user** tool; it does not authenticate users or expose an API.
- No transaction data is sent to an external service. Uploaded bytes are processed in memory and saved details are stored in the local SQLite file.
- The synthetic sample data is fictional and intended for demonstration.
- Matching is exact-reference based. There is no fuzzy matching, amount tolerance, or cross-currency conversion.
- Currency is captured for reporting but amounts are compared as signed values without FX conversion.
- Dates are compared at day granularity; time-of-day differences are ignored.
- A duplicate reference is reported as a duplicate case even if the other source has no corresponding record. Review notes identify the duplication.

## Troubleshooting

**`streamlit: command not found`**  
Activate the virtual environment first: `source .venv/bin/activate`, then reinstall dependencies.

**Port 8501 is already in use**  
Run `streamlit run app.py --server.port 8502`.

**A CSV is rejected for missing columns**  
Check the header names against the table above. The four required logical columns are `reference`, `amount`, `transaction_date`, and `status`.

**A row is rejected as an invalid amount or date**  
The error panel lists the CSV row and field. Amounts must be numeric currency values; dates must be parseable calendar dates or timestamps.

**History does not appear**  
Confirm the `data/` directory is writable. If `RECON_DB_PATH` is set, ensure its parent directory is writable.
