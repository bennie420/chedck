"""
test_sequence.py — Tests for src/sequence.py

Verifies gapless serial allocation, VOID recording, status updates,
and concurrent-safe behavior.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import sequence


@pytest.fixture
def db(tmp_path):
    """Provide a fresh, initialized in-memory-ish database for each test."""
    db_path = tmp_path / "test_checks.db"
    sequence.init_db(db_path)
    conn = sequence.get_connection(db_path)
    yield conn
    conn.close()


class TestSerialAllocation:
    def test_first_serial_is_1001(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        assert serial == 1001

    def test_serials_are_sequential(self, db):
        s1 = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        s2 = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        s3 = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        assert s1 == 1001
        assert s2 == 1002
        assert s3 == 1003

    def test_different_accounts_independent(self, db):
        """Different accounts share the global serial counter but are tagged separately."""
        a1 = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        a2 = sequence.allocate_serial("secondary", db)
        db.execute("COMMIT")
        # Serials are globally sequential — a2 follows a1
        assert a1 == 1001
        assert a2 == 1002
        # But each check is tagged to its own account
        rec1 = sequence.get_check_record(a1, db)
        rec2 = sequence.get_check_record(a2, db)
        assert rec1["account_id"] == "primary"
        assert rec2["account_id"] == "secondary"

    def test_serial_record_created(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        record = sequence.get_check_record(serial, db)
        assert record is not None
        assert record["serial_number"] == serial
        assert record["status"] == "allocated"


class TestPopulateRecord:
    def test_populate_fills_fields(self, db):
        serial = sequence.allocate_serial("primary", db)
        sequence.populate_check_record(
            serial=serial,
            routing_number="021000021",
            payee_name="Acme Corp",
            amount_cents=125000,
            issue_date="2026-09-19",
            conn=db,
        )
        db.execute("COMMIT")
        record = sequence.get_check_record(serial, db)
        assert record["payee_name"] == "Acme Corp"
        assert record["amount_cents"] == 125000
        assert record["routing_number"] == "021000021"


class TestStatusUpdates:
    def test_update_to_printed(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        sequence.update_status(serial, "printed", db)
        record = sequence.get_check_record(serial, db)
        assert record["status"] == "printed"

    def test_invalid_status_raises(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        with pytest.raises(ValueError, match="Invalid status"):
            sequence.update_status(serial, "banana", db)

    def test_all_valid_statuses_accepted(self, db):
        valid = ["allocated", "printed", "voided", "spoiled", "cleared", "stopped", "mismatch"]
        for i, status in enumerate(valid):
            serial = sequence.allocate_serial("primary", db)
            db.execute("COMMIT")
            sequence.update_status(serial, status, db)
            record = sequence.get_check_record(serial, db)
            assert record["status"] == status


class TestVoid:
    def test_void_changes_status(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        db.execute("BEGIN")
        sequence.void_check(serial, "Test void", "operator1", db)
        db.execute("COMMIT")
        record = sequence.get_check_record(serial, db)
        assert record["status"] == "voided"

    def test_void_nonexistent_serial(self, db):
        with pytest.raises(ValueError, match="does not exist"):
            sequence.void_check(9999, "Test", "op", db)

    def test_cannot_void_cleared_check(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        sequence.update_status(serial, "cleared", db)
        with pytest.raises(ValueError, match="already cleared"):
            sequence.void_check(serial, "Test", "op", db)


class TestUnprotectedAlert:
    def test_printed_with_no_positive_pay_returned(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        sequence.update_status(serial, "printed", db)
        unprotected = sequence.get_unprotected_printed_checks(db)
        assert any(u["serial_number"] == serial for u in unprotected)

    def test_check_with_positive_pay_not_returned(self, db):
        serial = sequence.allocate_serial("primary", db)
        db.execute("COMMIT")
        # Update status to printed WITH positive_pay_export_id set.
        # We bypass FK by setting pragma off temporarily.
        db.execute("PRAGMA foreign_keys=OFF")
        sequence.update_status(
            serial, "printed", db,
            positive_pay_export_id=1,
        )
        db.execute("PRAGMA foreign_keys=ON")
        unprotected = sequence.get_unprotected_printed_checks(db)
        assert not any(u["serial_number"] == serial for u in unprotected)


class TestPrintBatch:
    def test_create_and_finish_batch(self, db):
        batch_id = sequence.start_print_batch("operator1", "HP-LaserJet", "CART123", db)
        assert batch_id is not None
        assert batch_id > 0
        sequence.finish_print_batch(batch_id, db)
        row = db.execute(
            "SELECT * FROM print_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        assert row["finished_at"] is not None


class TestCustomSerialAllocation:
    """Verifies user-specified check serial numbers and regulatory duplicate protection."""

    def test_custom_serial_allocated_and_advances_counter(self, db):
        next_before = sequence.get_next_serial(db)
        requested = 50000
        serial = sequence.allocate_serial("primary", db, requested_serial=requested)
        db.execute("COMMIT")
        assert serial == requested
        next_after = sequence.get_next_serial(db)
        assert next_after == requested + 1

    def test_duplicate_serial_rejected(self, db):
        serial = sequence.allocate_serial("primary", db, requested_serial=8800)
        sequence.populate_check_record(
            serial=serial,
            routing_number="011900445",
            payee_name="Test Payee",
            amount_cents=10000,
            issue_date="2026-09-20",
            conn=db,
        )
        db.execute("COMMIT")

        with pytest.raises(ValueError, match="already exists in the ledger"):
            sequence.allocate_serial("primary", db, requested_serial=8800)

    def test_invalid_range_rejected(self, db):
        with pytest.raises(ValueError, match="positive"):
            sequence.allocate_serial("primary", db, requested_serial=0)

        with pytest.raises(ValueError, match="exceeds 10 digits"):
            sequence.allocate_serial("primary", db, requested_serial=10_000_000_000)

