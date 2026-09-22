"""
test_reconciliation.py — Tests for src/reconciliation.py

Verifies CSV parsing, clean matches, amount mismatches, payee mismatches,
unknown serials, and stop-payment violations.
"""

import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit
import reconciliation
import sequence


BANK_CONFIG = {
    "reconciliation": {
        "format": "csv",
        "csv_columns": {
            "serial": "CheckNumber",
            "cleared_date": "PostDate",
            "amount": "Amount",
            "payee": "Description",
        },
    }
}


def make_csv(rows: list[dict]) -> str:
    """Build a CSV string from a list of row dicts."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["CheckNumber", "PostDate", "Amount", "Description"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


@pytest.fixture
def checks_db(tmp_path):
    db_path = tmp_path / "checks.db"
    sequence.init_db(db_path)
    conn = sequence.get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def audit_conn(tmp_path):
    db_path = tmp_path / "audit.db"
    audit.init_audit_db(db_path)
    conn = audit.get_audit_connection(db_path)
    yield conn
    conn.close()


def seed_check(conn, serial=1001, payee="Acme Corp", amount_cents=125000):
    """Seed a printed check directly into the database for testing."""
    now = "2026-09-19T00:00:00Z"
    conn.execute("BEGIN")
    conn.execute(
        """
        INSERT INTO checks
            (serial_number, account_id, routing_number, payee_name,
             amount_cents, issue_date, status, created_at, updated_at)
        VALUES (?, 'primary', '021000021', ?, ?, '2026-09-19', 'printed', ?, ?)
        """,
        (serial, payee, amount_cents, now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO serial_counter (account_id, last_serial) VALUES ('global', ?)",
        (serial,),
    )
    conn.execute("COMMIT")


class TestLoadCSV:
    def test_parse_single_row(self, tmp_path):
        csv_content = make_csv([{
            "CheckNumber": "1001",
            "PostDate": "09/19/2026",
            "Amount": "1250.00",
            "Description": "Acme Corp",
        }])
        file_path = tmp_path / "recon.csv"
        file_path.write_text(csv_content)

        items = reconciliation.load_recon_file(file_path, BANK_CONFIG)
        assert len(items) == 1
        assert items[0]["serial"] == 1001
        assert items[0]["cleared_amount_cents"] == 125000
        assert items[0]["payee"] == "Acme Corp"

    def test_non_check_row_has_no_serial(self, tmp_path):
        csv_content = make_csv([{
            "CheckNumber": "",
            "PostDate": "09/19/2026",
            "Amount": "50.00",
            "Description": "Wire transfer fee",
        }])
        file_path = tmp_path / "recon.csv"
        file_path.write_text(csv_content)

        items = reconciliation.load_recon_file(file_path, BANK_CONFIG)
        assert items[0]["serial"] is None


class TestReconcile:
    def test_clean_match_clears_check(self, checks_db, audit_conn, tmp_path):
        seed_check(checks_db)

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 125000,
            "payee": "Acme Corp",
        }]

        checks_db.execute("BEGIN")
        result = reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        assert result["matched"] == 1
        assert result["mismatches"] == []

        record = sequence.get_check_record(1001, checks_db)
        assert record["status"] == "cleared"
        assert record["cleared_amount_cents"] == 125000

    def test_amount_mismatch_flagged(self, checks_db, audit_conn):
        seed_check(checks_db, amount_cents=125000)

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 999999,  # Wrong amount
            "payee": "Acme Corp",
        }]

        checks_db.execute("BEGIN")
        result = reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        assert result["matched"] == 0
        assert len(result["mismatches"]) == 1
        assert "AMOUNT_MISMATCH" in result["mismatches"][0]["mismatch_reason"]

        record = sequence.get_check_record(1001, checks_db)
        assert record["status"] == "mismatch"

    def test_payee_mismatch_flagged(self, checks_db, audit_conn):
        seed_check(checks_db, payee="Acme Corp")

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 125000,
            "payee": "Totally Different Payee",
        }]

        checks_db.execute("BEGIN")
        result = reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        assert len(result["mismatches"]) == 1
        assert "PAYEE_MISMATCH" in result["mismatches"][0]["mismatch_reason"]

    def test_unknown_serial_flagged(self, checks_db, audit_conn):
        cleared_items = [{
            "serial": 9999,  # Not in ledger
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 50000,
            "payee": "Unknown",
        }]

        checks_db.execute("BEGIN")
        result = reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        assert 9999 in result["unknown_serials"]
        assert len(result["mismatches"]) == 1

    def test_stopped_check_flagged(self, checks_db, audit_conn):
        seed_check(checks_db)
        sequence.update_status(1001, "stopped", checks_db)

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 125000,
            "payee": "Acme Corp",
        }]

        checks_db.execute("BEGIN")
        result = reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        assert len(result["mismatches"]) == 1
        assert "CLEARED_AFTER_STOP" in result["mismatches"][0]["mismatch_reason"]

    def test_recon_mismatch_audit_event_logged(self, checks_db, audit_conn):
        seed_check(checks_db, amount_cents=125000)

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 200000,  # Mismatch
            "payee": "Acme Corp",
        }]

        checks_db.execute("BEGIN")
        reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        events = audit.get_events_by_type("RECON_MISMATCH", audit_conn)
        assert len(events) >= 1

    def test_clean_match_audit_event_logged(self, checks_db, audit_conn):
        seed_check(checks_db)

        cleared_items = [{
            "serial": 1001,
            "cleared_date": "2026-09-22",
            "cleared_amount_cents": 125000,
            "payee": "Acme Corp",
        }]

        checks_db.execute("BEGIN")
        reconciliation.reconcile(cleared_items, checks_db, audit_conn)
        checks_db.execute("COMMIT")

        events = audit.get_events_by_type("RECON_MATCHED", audit_conn)
        assert len(events) == 1
