"""SQLite persistence for reconciliation runs."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from recon.engine import DETAIL_COLUMNS, ReconciliationResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "reconciliation.db"

RESULT_DB_COLUMNS = [
    "reference",
    "result",
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


@dataclass
class SavedRun:
    run_id: int
    created_at: str
    core_filename: str
    provider_filename: str
    summary: dict[str, Any]
    details: pd.DataFrame


def _resolve_path(db_path: str | Path | None = None) -> Path:
    configured = db_path or os.environ.get("RECON_DB_PATH") or DEFAULT_DB_PATH
    return Path(configured).expanduser().resolve()


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: str | Path | None = None) -> Path:
    """Create the SQLite schema if it does not already exist."""

    path = _resolve_path(db_path)
    with closing(_connect(path)) as connection, connection:
        connection.executescript(
            """
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
            """
        )
    return path


def _db_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def save_reconciliation(
    result: ReconciliationResult, db_path: str | Path | None = None
) -> int:
    """Persist a reconciliation run and all of its result rows."""

    initialize_database(db_path)
    created_at = result.generated_at.astimezone(timezone.utc).isoformat(timespec="seconds")
    summary = result.summary

    with closing(_connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO reconciliation_runs (
                created_at, core_filename, provider_filename,
                core_transactions, provider_transactions, total_transactions,
                matched, discrepancies, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                result.core_filename,
                result.provider_filename,
                int(summary["core_transactions"]),
                int(summary["provider_transactions"]),
                int(summary["total_transactions"]),
                int(summary["matched"]),
                int(summary["discrepancies"]),
                json.dumps(summary, default=str),
            ),
        )
        run_id = int(cursor.lastrowid)

        rows = []
        for record in result.details.to_dict(orient="records"):
            rows.append(
                tuple(
                    run_id if column == "run_id" else _db_value(record.get(column))
                    for column in ["run_id", *RESULT_DB_COLUMNS]
                )
            )

        placeholders = ", ".join("?" for _ in range(len(RESULT_DB_COLUMNS) + 1))
        connection.executemany(
            f"""
            INSERT INTO reconciliation_results (
                run_id, {", ".join(RESULT_DB_COLUMNS)}
            ) VALUES ({placeholders})
            """,
            rows,
        )

    return run_id


def list_runs(
    limit: int = 20, db_path: str | Path | None = None
) -> pd.DataFrame:
    """Return recent runs, newest first, for the history view."""

    initialize_database(db_path)
    with closing(_connect(db_path)) as connection:
        frame = pd.read_sql_query(
            """
            SELECT
                id AS run_id,
                created_at,
                core_filename,
                provider_filename,
                total_transactions,
                matched,
                discrepancies,
                summary_json
            FROM reconciliation_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            connection,
            params=(max(1, int(limit)),),
        )

    if frame.empty:
        return frame

    summaries = []
    for payload in frame.pop("summary_json"):
        try:
            summaries.append(json.loads(payload))
        except (TypeError, json.JSONDecodeError):
            summaries.append({})

    frame["amount_mismatches"] = [
        summary.get("amount_mismatches", 0) for summary in summaries
    ]
    frame["missing_total"] = [summary.get("missing_total", 0) for summary in summaries]
    frame["duplicates"] = [summary.get("duplicates", 0) for summary in summaries]
    return frame


def get_run(run_id: int, db_path: str | Path | None = None) -> SavedRun | None:
    """Fetch one saved run with its detailed result rows."""

    initialize_database(db_path)
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM reconciliation_runs WHERE id = ?", (int(run_id),)
        ).fetchone()
        if row is None:
            return None

        details = pd.read_sql_query(
            f"""
            SELECT {", ".join(RESULT_DB_COLUMNS)}
            FROM reconciliation_results
            WHERE run_id = ?
            ORDER BY id
            """,
            connection,
            params=(int(run_id),),
        )

    try:
        summary = json.loads(row["summary_json"])
    except (TypeError, json.JSONDecodeError):
        summary = {}

    details = details.reindex(columns=DETAIL_COLUMNS)
    return SavedRun(
        run_id=int(row["id"]),
        created_at=str(row["created_at"]),
        core_filename=str(row["core_filename"]),
        provider_filename=str(row["provider_filename"]),
        summary=summary,
        details=details,
    )


def format_utc_timestamp(value: str | datetime) -> str:
    """Display a stored ISO timestamp in a compact UTC format."""

    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
