"""
positive_pay.py — Positive Pay issue file generation.

Generates the Positive Pay issue file in the bank's required format
and registers the export in the checks database.

Per buildspec.md §11:
  "Generate the Positive Pay issue file in the same transaction that
   allocates the serial number, so a printed check that never reaches
   the bank's issue file is impossible."

This module writes the issue file to disk and records the export in the
positive_pay_exports table. The actual upload to the bank is done by
scripts/export_positive_pay.py (manual or scheduled).

Supported formats: CSV (default), extensible to XML/NACHA.
"""

import csv
import datetime
import hashlib
import io
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

def generate_issue_file(
    check_records: list[dict],
    bank_config: dict,
    output_dir: str | Path,
) -> tuple[Path, str]:
    """
    Generate a Positive Pay issue file for the given check records.

    Parameters
    ----------
    check_records : list of check record dicts (from sequence.get_check_record)
    bank_config   : loaded bank_config.json dict
    output_dir    : directory to write the file into

    Returns (file_path, sha256_hex) of the generated file.

    Raises ValueError if check_records is empty or a record is missing
    required fields.
    """
    if not check_records:
        raise ValueError("Cannot generate a Positive Pay file with no check records")

    pp_cfg     = bank_config.get("positive_pay", {})
    fmt        = pp_cfg.get("format", "csv").lower()
    date_fmt   = pp_cfg.get("date_format", "%m/%d/%Y")

    if fmt == "csv":
        content, extension = _generate_csv(check_records, pp_cfg, date_fmt)
    else:
        raise ValueError(
            f"Unsupported Positive Pay format: {fmt!r}. "
            "Update config/bank_config.json positive_pay.format to 'csv'."
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp  = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    file_path  = output_dir / f"positive_pay_{timestamp}.{extension}"
    file_path.write_text(content, encoding="utf-8")

    sha256_hex = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return file_path, sha256_hex


def _generate_csv(
    check_records: list[dict],
    pp_cfg: dict,
    date_fmt: str,
) -> tuple[str, str]:
    """Generate CSV content. Returns (content_str, file_extension)."""
    fields_order = pp_cfg.get(
        "fields_order",
        ["account_number", "check_number", "issue_date", "amount", "payee_name", "void_flag"],
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields_order)  # Header row

    for rec in check_records:
        _validate_record(rec)

        # Format issue_date
        try:
            issue_date = datetime.datetime.strptime(
                rec["issue_date"], "%Y-%m-%d"
            ).strftime(date_fmt)
        except (ValueError, KeyError):
            issue_date = rec.get("issue_date", "")

        # Format amount as dollars and cents
        amount_cents = rec["amount_cents"]
        amount_str   = f"{amount_cents // 100}.{amount_cents % 100:02d}"

        void_flag = "V" if rec.get("status") == "voided" else ""

        field_map = {
            "account_number": rec.get("account_number", rec.get("account_id", "")),
            "check_number":   str(rec["serial_number"]),
            "issue_date":     issue_date,
            "amount":         amount_str,
            "payee_name":     rec["payee_name"],
            "void_flag":      void_flag,
        }

        row = [field_map.get(f, "") for f in fields_order]
        writer.writerow(row)

    return buf.getvalue(), "csv"


def _validate_record(rec: dict) -> None:
    """Raise ValueError if a check record is missing required Positive Pay fields."""
    required = ["serial_number", "payee_name", "amount_cents", "issue_date"]
    for field in required:
        if field not in rec or rec[field] is None:
            raise ValueError(
                f"Check record is missing required field {field!r} for Positive Pay: {rec}"
            )


# ---------------------------------------------------------------------------
# Database registration
# ---------------------------------------------------------------------------

def register_export(
    file_path: Path,
    sha256_hex: str,
    serial_numbers: list[int],
    conn: sqlite3.Connection,
) -> int:
    """
    Register the Positive Pay export in the database and link each serial
    to the export record.

    Must be called within the same transaction that allocated the serials.

    Returns the positive_pay_exports row ID.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


    cursor = conn.execute(
        """
        INSERT INTO positive_pay_exports
            (exported_at, file_path, file_hash, bank_ack_status)
        VALUES (?, ?, ?, 'pending')
        """,
        (now, str(file_path), sha256_hex),
    )
    export_id = cursor.lastrowid

    for serial in serial_numbers:
        conn.execute(
            """
            UPDATE checks
            SET positive_pay_export_id = ?, updated_at = ?
            WHERE serial_number = ?
            """,
            (export_id, now, serial),
        )

    return export_id


def mark_bank_acknowledged(
    export_id: int,
    status: str,
    conn: sqlite3.Connection,
) -> None:
    """
    Update the bank acknowledgement status for a Positive Pay export.

    status should be one of: 'accepted', 'rejected', 'pending'.
    """
    conn.execute(
        "UPDATE positive_pay_exports SET bank_ack_status = ? WHERE id = ?",
        (status, export_id),
    )


# ---------------------------------------------------------------------------
# Alert: unprotected printed checks
# ---------------------------------------------------------------------------

def check_for_unprotected_items(conn: sqlite3.Connection) -> list[dict]:
    """
    Return any printed checks that do not yet have a Positive Pay export.
    These are live items at risk. Log an alert and surface to the operator.
    """
    rows = conn.execute(
        """
        SELECT serial_number, payee_name, amount_cents, issue_date, status
        FROM checks
        WHERE status = 'printed'
          AND positive_pay_export_id IS NULL
        ORDER BY serial_number
        """
    ).fetchall()
    return [dict(r) for r in rows]
