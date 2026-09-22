"""
audit.py — Immutable append-only audit log.

All significant events in the check printing system are recorded here.
The audit database is separate from the checks database so that access
to print check data does not imply access to audit history.

Immutability is enforced at the SQLite level via triggers that raise
an error on UPDATE or DELETE of audit_events rows.

Event types (buildspec.md §11):
  ALLOCATED              — serial number allocated
  PRINTED                — check physically printed
  VOIDED                 — check voided before printing
  SPOILED                — check spoiled after printing (physical destroy)
  SIGNATURE_RELEASED     — digital signature applied
  POSITIVE_PAY_EXPORTED  — Positive Pay issue file generated and queued
  RECON_MATCHED          — bank reconciliation: check matched and cleared
  RECON_MISMATCH         — bank reconciliation: amount or payee mismatch
  REPRINT                — check reprinted (spoilage replacement)
  VAULT_UNLOCKED         — signature vault accessed
  CONFIG_CHANGED         — configuration file modified
  STARTUP                — pipeline startup with config validation
"""

import sqlite3
import datetime
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT    NOT NULL,
    serial       INTEGER,
    operator_id  TEXT    NOT NULL,
    details_json TEXT,
    recorded_at  TEXT    NOT NULL
);

-- Immutability triggers: block any UPDATE or DELETE on audit_events.
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'Audit records are immutable: UPDATE is not permitted');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'Audit records are immutable: DELETE is not permitted');
END;
"""

_VALID_EVENT_TYPES = {
    "ALLOCATED",
    "PRINTED",
    "VOIDED",
    "SPOILED",
    "SIGNATURE_RELEASED",
    "POSITIVE_PAY_EXPORTED",
    "RECON_MATCHED",
    "RECON_MISMATCH",
    "REPRINT",
    "VAULT_UNLOCKED",
    "CONFIG_CHANGED",
    "STARTUP",
}


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_audit_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open the audit database with WAL mode."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_audit_db(db_path: str | Path) -> None:
    """Create the audit table and immutability triggers."""
    conn = get_audit_connection(db_path)
    conn.executescript(_SCHEMA)
    conn.close()


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------

def log_event(
    conn: sqlite3.Connection,
    event_type: str,
    operator_id: str,
    serial: int | None = None,
    **details,
) -> int:
    """
    Append an event to the audit log.

    Parameters
    ----------
    conn         : open audit database connection
    event_type   : one of _VALID_EVENT_TYPES
    operator_id  : the user/system identity performing the action
    serial       : check serial number (None for system events)
    **details    : arbitrary key-value pairs serialized to JSON

    Returns the new row ID.
    Raises ValueError for unknown event_type.
    """
    if event_type not in _VALID_EVENT_TYPES:
        raise ValueError(
            f"Unknown audit event type {event_type!r}. "
            f"Valid types: {sorted(_VALID_EVENT_TYPES)}"
        )

    details_json = json.dumps(details, default=str) if details else None

    cursor = conn.execute(
        """
        INSERT INTO audit_events
            (event_type, serial, operator_id, details_json, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_type, serial, operator_id, details_json, _now()),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_events_for_serial(
    serial: int,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Return all audit events for a given serial number, oldest first."""
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE serial = ? ORDER BY id",
        (serial,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_recent_events(
    conn: sqlite3.Connection,
    limit: int = 100,
) -> list[dict]:
    """Return the most recent audit events."""
    rows = conn.execute(
        "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_events_by_type(
    event_type: str,
    conn: sqlite3.Connection,
    limit: int = 1000,
) -> list[dict]:
    """Return audit events of a specific type."""
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
        (event_type, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("details_json"):
        try:
            d["details"] = json.loads(d["details_json"])
        except json.JSONDecodeError:
            d["details"] = {}
    else:
        d["details"] = {}
    return d


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

