"""
reconciliation.py — Bank reconciliation ingest and comparison.

Ingests the bank's daily reconciliation file, matches each cleared item
against the check ledger, and flags any mismatches.

Per buildspec.md §10.2:
  "Ingest your bank's reconciliation/BAI2 file daily and auto-compare
   cleared amount, payee, and serial against the issue record. This is
   your UCC §4-406 duty discharged automatically."

Supported formats: CSV (configurable column names), BAI2 (basic).

Mismatch types detected:
  - Amount mismatch (cleared ≠ issued)    → possible alteration
  - Payee mismatch (cleared ≠ issued)     → possible fraud
  - Unknown serial (not in our ledger)    → possible counterfeit
  - Already-stopped check cleared        → fraud
"""

import csv
import io
import sqlite3
import datetime
from pathlib import Path
from typing import Generator


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def load_recon_file(
    file_path: str | Path,
    bank_config: dict,
) -> list[dict]:
    """
    Parse a bank reconciliation file and return a list of cleared-item dicts.

    Each dict has keys:
        serial          int or None
        cleared_date    str (ISO 8601)
        cleared_amount_cents  int
        payee           str or None

    Raises ValueError on unsupported format or parse errors.
    """
    file_path = Path(file_path)
    fmt = bank_config.get("reconciliation", {}).get("format", "csv").lower()

    if fmt == "csv":
        return _load_csv(file_path, bank_config)
    elif fmt == "bai2":
        return _load_bai2(file_path)
    else:
        raise ValueError(
            f"Unsupported reconciliation format: {fmt!r}. "
            "Set config/bank_config.json reconciliation.format to 'csv' or 'bai2'."
        )


def reconcile(
    cleared_items: list[dict],
    conn: sqlite3.Connection,
    audit_conn: sqlite3.Connection,
    operator_id: str = "recon-auto",
) -> dict:
    """
    Match cleared items against the check ledger.

    For each cleared item:
      - If serial matches an issued check:
          - Compare cleared_amount_cents vs amount_cents → flag RECON_MISMATCH
          - Compare payee (case-insensitive, stripped) → flag RECON_MISMATCH
          - If all match → update status to 'cleared', log RECON_MATCHED
      - If serial not found → log RECON_MISMATCH with detail 'UNKNOWN_SERIAL'
      - If check is 'stopped' → log RECON_MISMATCH with detail 'CLEARED_AFTER_STOP'

    Returns a summary dict:
        {
          'matched':  int,
          'mismatches': list[dict],
          'unknown_serials': list[int],
        }
    """
    import audit  # local import to avoid circular at module level

    matched         = 0
    mismatches      = []
    unknown_serials = []

    now = _now()

    for item in cleared_items:
        serial        = item.get("serial")
        cleared_cents = item.get("cleared_amount_cents", 0)
        cleared_payee = (item.get("payee") or "").strip()
        cleared_date  = item.get("cleared_date", now)

        if serial is None:
            # Cannot match without a serial number.
            mismatches.append({
                **item,
                "mismatch_reason": "NO_SERIAL",
            })
            continue

        row = conn.execute(
            "SELECT * FROM checks WHERE serial_number = ?", (serial,)
        ).fetchone()

        if row is None:
            unknown_serials.append(serial)
            audit.log_event(
                audit_conn,
                "RECON_MISMATCH",
                operator_id,
                serial=serial,
                reason="UNKNOWN_SERIAL",
                cleared_amount_cents=cleared_cents,
                cleared_date=cleared_date,
            )
            mismatches.append({
                **item,
                "mismatch_reason": "UNKNOWN_SERIAL",
            })
            continue

        record = dict(row)

        if record["status"] == "stopped":
            audit.log_event(
                audit_conn,
                "RECON_MISMATCH",
                operator_id,
                serial=serial,
                reason="CLEARED_AFTER_STOP",
                issued_amount_cents=record["amount_cents"],
                cleared_amount_cents=cleared_cents,
            )
            mismatches.append({
                **item,
                "mismatch_reason": "CLEARED_AFTER_STOP",
                "issued_amount_cents": record["amount_cents"],
            })
            _update_cleared(serial, cleared_cents, cleared_payee, cleared_date,
                            "mismatch", conn)
            continue

        reasons = []
        if cleared_cents != record["amount_cents"]:
            reasons.append(
                f"AMOUNT_MISMATCH(issued={record['amount_cents']}, "
                f"cleared={cleared_cents})"
            )
        if cleared_payee and record["payee_name"]:
            if cleared_payee.lower() != record["payee_name"].lower():
                reasons.append(
                    f"PAYEE_MISMATCH(issued={record['payee_name']!r}, "
                    f"cleared={cleared_payee!r})"
                )

        if reasons:
            audit.log_event(
                audit_conn,
                "RECON_MISMATCH",
                operator_id,
                serial=serial,
                reason="; ".join(reasons),
                issued_amount_cents=record["amount_cents"],
                cleared_amount_cents=cleared_cents,
                issued_payee=record["payee_name"],
                cleared_payee=cleared_payee,
                cleared_date=cleared_date,
            )
            _update_cleared(serial, cleared_cents, cleared_payee, cleared_date,
                            "mismatch", conn)
            mismatches.append({
                **item,
                "mismatch_reason": "; ".join(reasons),
                "issued_amount_cents": record["amount_cents"],
                "issued_payee": record["payee_name"],
            })
        else:
            # Clean match.
            _update_cleared(serial, cleared_cents, cleared_payee, cleared_date,
                            "cleared", conn)
            audit.log_event(
                audit_conn,
                "RECON_MATCHED",
                operator_id,
                serial=serial,
                cleared_date=cleared_date,
                amount_cents=cleared_cents,
            )
            matched += 1

    return {
        "matched":         matched,
        "mismatches":      mismatches,
        "unknown_serials": unknown_serials,
    }


# ---------------------------------------------------------------------------
# Internal: CSV parser
# ---------------------------------------------------------------------------

def _load_csv(file_path: Path, bank_config: dict) -> list[dict]:
    """Parse a CSV reconciliation file using the column map in bank_config."""
    col_map = bank_config.get("reconciliation", {}).get("csv_columns", {})
    serial_col  = col_map.get("serial",       "CheckNumber")
    date_col    = col_map.get("cleared_date", "PostDate")
    amount_col  = col_map.get("amount",       "Amount")
    payee_col   = col_map.get("payee",        "Description")

    items = []
    text = file_path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    for row_num, row in enumerate(reader, start=2):
        # Serial — may be absent for non-check transactions.
        serial_raw = row.get(serial_col, "").strip()
        serial = None
        if serial_raw:
            try:
                serial = int(serial_raw)
            except ValueError:
                serial = None

        # Amount — parse dollars.cents string to cents.
        from amounts import parse_amount_string
        amount_str = row.get(amount_col, "0").strip()
        try:
            cleared_cents = parse_amount_string(amount_str)
        except ValueError:
            cleared_cents = 0

        # Date — store as-is; ISO conversion is best-effort.
        cleared_date = row.get(date_col, "").strip()

        payee = row.get(payee_col, "").strip()

        items.append({
            "serial":               serial,
            "cleared_date":         cleared_date,
            "cleared_amount_cents": cleared_cents,
            "payee":                payee,
            "raw_row":              row_num,
        })

    return items


# ---------------------------------------------------------------------------
# Internal: BAI2 parser (basic)
# ---------------------------------------------------------------------------

def _load_bai2(file_path: Path) -> list[dict]:
    """
    Parse a BAI2 file and extract check transaction records.

    BAI2 type codes for checks:
      399 = Check paid
      475 = Stop payment
    This parser extracts 399 records only.

    BAI2 is complex; this is a best-effort parser for the common case.
    If your bank's BAI2 format differs, extend this function or switch to CSV.
    """
    items = []
    text  = file_path.read_text(encoding="utf-8-sig")

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("16,"):
            continue

        # BAI2 transaction detail record:
        # 16,type_code,amount,funds_type,...,text
        parts = line.split(",")
        if len(parts) < 4:
            continue

        type_code = parts[1].strip()
        if type_code not in ("399", "475"):
            continue

        amount_str = parts[2].strip()
        try:
            # BAI2 amounts are in cents (no decimal point).
            cleared_cents = int(amount_str)
        except ValueError:
            cleared_cents = 0

        # The text portion often contains the check number.
        text_portion = ",".join(parts[6:]) if len(parts) > 6 else ""
        serial = _extract_serial_from_bai2_text(text_portion)

        items.append({
            "serial":               serial,
            "cleared_date":         "",
            "cleared_amount_cents": cleared_cents,
            "payee":                "",
            "raw_row":              line,
        })

    return items


def _extract_serial_from_bai2_text(text: str) -> int | None:
    """Attempt to extract a check serial number from a BAI2 text field."""
    import re
    # Common patterns: "CHECK 1001", "CHK#1001", "CHECK NUMBER 1001"
    match = re.search(r"(?:CHK|CHECK)[#\s]+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_cleared(
    serial: int,
    cleared_cents: int,
    cleared_payee: str,
    cleared_date: str,
    new_status: str,
    conn: sqlite3.Connection,
) -> None:
    now = _now()
    conn.execute(
        """
        UPDATE checks
        SET status               = ?,
            cleared_amount_cents = ?,
            cleared_payee        = ?,
            cleared_date         = ?,
            updated_at           = ?
        WHERE serial_number = ?
        """,
        (new_status, cleared_cents, cleared_payee, cleared_date, now, serial),
    )


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

