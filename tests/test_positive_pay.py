"""
test_positive_pay.py — Tests for src/positive_pay.py

Verifies CSV generation, database registration, and the unprotected-check alert.
"""

import csv
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import positive_pay
import sequence


BANK_CONFIG = {
    "positive_pay": {
        "format": "csv",
        "fields_order": ["account_number", "check_number", "issue_date", "amount", "payee_name", "void_flag"],
        "date_format": "%m/%d/%Y",
        "amount_format": "dollars_and_cents",
    },
    "reconciliation": {
        "format": "csv",
        "csv_columns": {
            "serial": "CheckNumber",
            "cleared_date": "PostDate",
            "amount": "Amount",
            "payee": "Description",
        },
    },
}

SAMPLE_RECORDS = [
    {
        "serial_number": 1001,
        "account_number": "123456789",
        "payee_name": "Acme Corp",
        "amount_cents": 125000,
        "issue_date": "2026-09-19",
        "status": "printed",
    }
]


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "checks.db"
    sequence.init_db(db_path)
    conn = sequence.get_connection(db_path)
    yield conn
    conn.close()


class TestGenerateIssueFile:
    def test_csv_generated(self, tmp_path):
        file_path, sha256 = positive_pay.generate_issue_file(
            SAMPLE_RECORDS, BANK_CONFIG, tmp_path
        )
        assert file_path.exists()
        assert file_path.suffix == ".csv"
        assert len(sha256) == 64  # SHA-256 hex

    def test_csv_content_correct(self, tmp_path):
        file_path, _ = positive_pay.generate_issue_file(
            SAMPLE_RECORDS, BANK_CONFIG, tmp_path
        )
        content = file_path.read_text()
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["check_number"] == "1001"
        assert rows[0]["payee_name"] == "Acme Corp"
        assert rows[0]["amount"] == "1250.00"

    def test_date_formatted_correctly(self, tmp_path):
        file_path, _ = positive_pay.generate_issue_file(
            SAMPLE_RECORDS, BANK_CONFIG, tmp_path
        )
        content = file_path.read_text()
        reader = csv.DictReader(io.StringIO(content))
        row = next(reader)
        assert row["issue_date"] == "09/19/2026"

    def test_voided_check_has_v_flag(self, tmp_path):
        voided = [{**SAMPLE_RECORDS[0], "status": "voided"}]
        file_path, _ = positive_pay.generate_issue_file(voided, BANK_CONFIG, tmp_path)
        content = file_path.read_text()
        reader = csv.DictReader(io.StringIO(content))
        row = next(reader)
        assert row["void_flag"] == "V"

    def test_empty_records_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no check records"):
            positive_pay.generate_issue_file([], BANK_CONFIG, tmp_path)

    def test_missing_required_field_raises(self, tmp_path):
        bad_record = {"serial_number": 1001}  # Missing payee_name, amount_cents, etc.
        with pytest.raises(ValueError, match="missing required field"):
            positive_pay.generate_issue_file([bad_record], BANK_CONFIG, tmp_path)


class TestRegisterExport:
    def test_export_registered_in_db(self, db, tmp_path):
        # Allocate a serial first
        serial = sequence.allocate_serial("primary", db)
        sequence.populate_check_record(serial, "021000021", "Acme", 100, "2026-09-19", db)
        db.execute("COMMIT")

        file_path, sha256 = positive_pay.generate_issue_file(
            [{**SAMPLE_RECORDS[0], "serial_number": serial}], BANK_CONFIG, tmp_path
        )
        export_id = positive_pay.register_export(file_path, sha256, [serial], db)

        assert export_id is not None
        row = db.execute(
            "SELECT * FROM positive_pay_exports WHERE id = ?", (export_id,)
        ).fetchone()
        assert row is not None
        assert row["file_hash"] == sha256

    def test_serial_linked_to_export(self, db, tmp_path):
        serial = sequence.allocate_serial("primary", db)
        sequence.populate_check_record(serial, "021000021", "Acme", 100, "2026-09-19", db)
        db.execute("COMMIT")

        file_path, sha256 = positive_pay.generate_issue_file(
            [{**SAMPLE_RECORDS[0], "serial_number": serial}], BANK_CONFIG, tmp_path
        )
        export_id = positive_pay.register_export(file_path, sha256, [serial], db)

        record = sequence.get_check_record(serial, db)
        assert record["positive_pay_export_id"] == export_id


class TestUnprotectedAlert:
    def test_printed_without_export_detected(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        sequence.update_status(serial, "printed", db)
        unprotected = positive_pay.check_for_unprotected_items(db)
        assert any(u["serial_number"] == serial for u in unprotected)
