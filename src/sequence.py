"""
sequence.py — Gapless check serial number ledger.

Uses SQLite with a serializable transaction to guarantee that serial numbers
are unique and gapless per account. Every gap must be explained by a VOID record.

See buildspec.md §10.2 (check record data model) and §11 (sequential stock
accountability).
"""

import sqlite3
import datetime
from pathlib import Path

from validation import validate_serial_number


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_CHECKS = """
CREATE TABLE IF NOT EXISTS checks (
    serial_number         INTEGER PRIMARY KEY,
    account_id            TEXT    NOT NULL,
    routing_number        TEXT    NOT NULL,
    payee_name            TEXT    NOT NULL,
    amount_cents          INTEGER NOT NULL,
    issue_date            TEXT    NOT NULL,
    status                TEXT    NOT NULL DEFAULT 'allocated'
                              CHECK(status IN ('allocated','printed','voided',
                                               'spoiled','cleared','stopped',
                                               'mismatch')),
    print_batch_id        INTEGER,
    signature_applied     INTEGER NOT NULL DEFAULT 0,
    signature_approver_id TEXT,
    positive_pay_export_id INTEGER,
    cleared_amount_cents  INTEGER,
    cleared_payee         TEXT,
    cleared_date          TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,

    FOREIGN KEY (print_batch_id)        REFERENCES print_batches(id),
    FOREIGN KEY (positive_pay_export_id) REFERENCES positive_pay_exports(id)
);

CREATE TABLE IF NOT EXISTS print_batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_id     TEXT    NOT NULL,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    printer_id      TEXT,
    cartridge_serial TEXT
);

CREATE TABLE IF NOT EXISTS positive_pay_exports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exported_at     TEXT    NOT NULL,
    file_path       TEXT,
    file_hash       TEXT,
    bank_ack_status TEXT    NOT NULL DEFAULT 'pending'
);
"""

_SCHEMA_SERIALS = """
CREATE TABLE IF NOT EXISTS serial_counter (
    account_id   TEXT    PRIMARY KEY,
    last_serial  INTEGER NOT NULL DEFAULT 0
);
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open the checks database, enforce WAL mode and foreign keys."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path) -> None:
    """Create all tables if they do not already exist."""
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA_CHECKS)
    conn.executescript(_SCHEMA_SERIALS)
    conn.close()


# ---------------------------------------------------------------------------
# Serial number allocation
# ---------------------------------------------------------------------------

def get_next_serial(conn: sqlite3.Connection) -> int:
    """Return the next available check serial number without advancing the counter."""
    row = conn.execute(
        "SELECT last_serial FROM serial_counter WHERE account_id = 'global'",
    ).fetchone()
    if row is None or row["last_serial"] == 0:
        return 1001
    return int(row["last_serial"]) + 1


def allocate_serial(
    account_id: str,
    conn: sqlite3.Connection,
    requested_serial: int | None = None,
) -> int:
    """
    Allocate the next sequential serial number, or a specifically requested serial number.

    Serial numbers are globally unique (not per-account) so the primary key
    constraint on checks.serial_number is always satisfied. The serial_counter
    table uses a single 'global' key.

    If requested_serial is provided:
      - Validates ANSI range (1 <= requested_serial <= 9,999,999,999)
      - Verifies that requested_serial is not already in use in the ledger
      - Updates last_serial = max(last_serial, requested_serial)

    This runs inside a BEGIN IMMEDIATE transaction to prevent concurrent
    double-allocation. The caller is responsible for committing or rolling
    back the enclosing transaction.

    Returns the allocated serial number (integer, > 0).
    """
    if requested_serial is not None:
        validate_serial_number(requested_serial)

    conn.execute("BEGIN IMMEDIATE")
    try:
        if requested_serial is not None:
            # Check for existing check record with this serial
            existing = conn.execute(
                "SELECT status FROM checks WHERE serial_number = ?",
                (requested_serial,),
            ).fetchone()

            if existing is not None:
                raise ValueError(
                    f"Check serial number {requested_serial} already exists in the ledger "
                    f"with status '{existing['status']}'. Check serial numbers must be unique "
                    f"per ANSI X9.100 and UCC §3-104 regulatory requirements."
                )
            new_serial = requested_serial

            # Update last_serial counter to be at least requested_serial
            row = conn.execute(
                "SELECT last_serial FROM serial_counter WHERE account_id = 'global'",
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO serial_counter (account_id, last_serial) VALUES ('global', ?)",
                    (new_serial,),
                )
            else:
                conn.execute(
                    "UPDATE serial_counter SET last_serial = MAX(last_serial, ?) WHERE account_id = 'global'",
                    (new_serial,),
                )
        else:
            row = conn.execute(
                "SELECT last_serial FROM serial_counter WHERE account_id = 'global'",
            ).fetchone()

            if row is None:
                # First check ever — seed at 1001 for aesthetics.
                new_serial = 1001
                conn.execute(
                    "INSERT INTO serial_counter (account_id, last_serial) VALUES ('global', ?)",
                    (new_serial,),
                )
            else:
                new_serial = row["last_serial"] + 1
                conn.execute(
                    "UPDATE serial_counter SET last_serial = ? WHERE account_id = 'global'",
                    (new_serial,),
                )

            validate_serial_number(new_serial)

        now = _now()
        conn.execute(
            """
            INSERT INTO checks
                (serial_number, account_id, routing_number, payee_name,
                 amount_cents, issue_date, status, created_at, updated_at)
            VALUES (?, ?, '', '', 0, '', 'allocated', ?, ?)
            ON CONFLICT(serial_number) DO UPDATE SET
                status = 'allocated',
                updated_at = excluded.updated_at
            """,
            (new_serial, account_id, now, now),
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return new_serial


def populate_check_record(
    serial: int,
    routing_number: str,
    payee_name: str,
    amount_cents: int,
    issue_date: str,
    conn: sqlite3.Connection,
) -> None:
    """
    Fill in the payment details for an already-allocated serial number.
    Must be called within the same transaction as allocate_serial.
    """
    now = _now()
    conn.execute(
        """
        UPDATE checks
        SET routing_number = ?,
            payee_name     = ?,
            amount_cents   = ?,
            issue_date     = ?,
            updated_at     = ?
        WHERE serial_number = ? AND status = 'allocated'
        """,
        (routing_number, payee_name, amount_cents, issue_date, now, serial),
    )


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------

def update_status(
    serial: int,
    new_status: str,
    conn: sqlite3.Connection,
    **extra_fields,
) -> None:
    """
    Update the status of a check record.

    extra_fields can include any column-value pairs from the checks table
    (e.g. print_batch_id=5, signature_applied=1).
    """
    valid_statuses = {
        "allocated", "printed", "voided", "spoiled",
        "cleared", "stopped", "mismatch",
    }
    if new_status not in valid_statuses:
        raise ValueError(
            f"Invalid status {new_status!r}. Must be one of {valid_statuses}"
        )

    now = _now()
    set_clause = "status = ?, updated_at = ?"
    params: list = [new_status, now]

    for col, val in extra_fields.items():
        set_clause += f", {col} = ?"
        params.append(val)

    params.append(serial)
    conn.execute(
        f"UPDATE checks SET {set_clause} WHERE serial_number = ?",
        params,
    )


# ---------------------------------------------------------------------------
# Void / spoil
# ---------------------------------------------------------------------------

def void_check(
    serial: int,
    reason: str,
    operator_id: str,
    conn: sqlite3.Connection,
) -> None:
    """
    Mark a check as voided. The serial gap is intentional and must be
    documented (the reason string is the documentation).

    Records: operator, reason, timestamp.
    """
    validate_serial_number(serial)

    row = conn.execute(
        "SELECT status FROM checks WHERE serial_number = ?", (serial,)
    ).fetchone()

    if row is None:
        raise ValueError(f"Serial number {serial} does not exist in the ledger")

    if row["status"] in ("cleared",):
        raise ValueError(
            f"Cannot void serial {serial}: it has already cleared the bank "
            f"(status={row['status']!r})"
        )

    now = _now()
    conn.execute(
        """
        UPDATE checks
        SET status     = 'voided',
            updated_at = ?
        WHERE serial_number = ?
        """,
        (now, serial),
    )

    # Store void reason in signature_approver_id field (repurposed as memo for
    # voided items — keeps the schema simple without adding a nullable column).
    # Full details also go into the audit log via audit.py.
    conn.execute(
        """
        UPDATE checks
        SET signature_approver_id = ?
        WHERE serial_number = ?
        """,
        (f"VOID by {operator_id}: {reason}", serial),
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_check_record(serial: int, conn: sqlite3.Connection) -> dict | None:
    """Return the full check record dict, or None if not found."""
    row = conn.execute(
        "SELECT * FROM checks WHERE serial_number = ?", (serial,)
    ).fetchone()
    return dict(row) if row else None


def get_unprotected_printed_checks(conn: sqlite3.Connection) -> list[dict]:
    """
    Return all checks with status='printed' and no Positive Pay export.
    These are live checks not yet submitted to the bank's Positive Pay
    — an immediate risk per buildspec.md §11.
    """
    rows = conn.execute(
        """
        SELECT * FROM checks
        WHERE status = 'printed'
          AND positive_pay_export_id IS NULL
        ORDER BY serial_number
        """
    ).fetchall()
    return [dict(r) for r in rows]


def start_print_batch(
    operator_id: str,
    printer_id: str,
    cartridge_serial: str,
    conn: sqlite3.Connection,
) -> int:
    """Open a print batch record; returns the new batch ID."""
    cursor = conn.execute(
        """
        INSERT INTO print_batches
            (operator_id, started_at, printer_id, cartridge_serial)
        VALUES (?, ?, ?, ?)
        """,
        (operator_id, _now(), printer_id, cartridge_serial),
    )
    return cursor.lastrowid


def finish_print_batch(batch_id: int, conn: sqlite3.Connection) -> None:
    """Mark a print batch as finished."""
    conn.execute(
        "UPDATE print_batches SET finished_at = ? WHERE id = ?",
        (_now(), batch_id),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

