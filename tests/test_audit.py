"""
test_audit.py — Tests for src/audit.py

Verifies: event logging, immutability triggers (UPDATE/DELETE blocked),
and query functions.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit


@pytest.fixture
def audit_db(tmp_path):
    db_path = tmp_path / "test_audit.db"
    audit.init_audit_db(db_path)
    conn = audit.get_audit_connection(db_path)
    yield conn
    conn.close()


class TestLogEvent:
    def test_log_returns_row_id(self, audit_db):
        row_id = audit.log_event(audit_db, "STARTUP", "test_operator")
        assert row_id is not None
        assert row_id > 0

    def test_log_all_event_types(self, audit_db):
        event_types = [
            "ALLOCATED", "PRINTED", "VOIDED", "SPOILED",
            "SIGNATURE_RELEASED", "POSITIVE_PAY_EXPORTED",
            "RECON_MATCHED", "RECON_MISMATCH", "REPRINT",
            "VAULT_UNLOCKED", "CONFIG_CHANGED", "STARTUP",
        ]
        for et in event_types:
            row_id = audit.log_event(audit_db, et, "op", serial=1001)
            assert row_id > 0, f"Failed to log event type {et}"

    def test_details_serialized_to_json(self, audit_db):
        audit.log_event(
            audit_db, "PRINTED", "op",
            serial=1001,
            payee="Acme",
            amount_cents=125000,
        )
        events = audit.get_events_for_serial(1001, audit_db)
        assert len(events) == 1
        assert events[0]["details"]["payee"] == "Acme"
        assert events[0]["details"]["amount_cents"] == 125000

    def test_unknown_event_type_raises(self, audit_db):
        with pytest.raises(ValueError, match="Unknown audit event type"):
            audit.log_event(audit_db, "BANANA", "op")

    def test_event_with_no_serial(self, audit_db):
        row_id = audit.log_event(audit_db, "STARTUP", "op", note="boot")
        assert row_id > 0


class TestImmutability:
    """The audit DB must block UPDATE and DELETE via triggers."""

    def test_update_blocked(self, audit_db):
        audit.log_event(audit_db, "STARTUP", "op")
        with pytest.raises(Exception, match="immutable"):
            audit_db.execute(
                "UPDATE audit_events SET operator_id = 'hacker' WHERE id = 1"
            )

    def test_delete_blocked(self, audit_db):
        audit.log_event(audit_db, "STARTUP", "op")
        with pytest.raises(Exception, match="immutable"):
            audit_db.execute("DELETE FROM audit_events WHERE id = 1")


class TestQueries:
    def test_get_events_for_serial(self, audit_db):
        audit.log_event(audit_db, "ALLOCATED", "op", serial=1001)
        audit.log_event(audit_db, "PRINTED",   "op", serial=1001)
        audit.log_event(audit_db, "ALLOCATED", "op", serial=1002)

        events = audit.get_events_for_serial(1001, audit_db)
        assert len(events) == 2
        assert all(e["serial"] == 1001 for e in events)

    def test_get_recent_events(self, audit_db):
        for i in range(5):
            audit.log_event(audit_db, "STARTUP", f"op{i}")
        recent = audit.get_recent_events(audit_db, limit=3)
        assert len(recent) == 3

    def test_get_events_by_type(self, audit_db):
        audit.log_event(audit_db, "PRINTED",  "op", serial=1001)
        audit.log_event(audit_db, "ALLOCATED", "op", serial=1001)
        audit.log_event(audit_db, "PRINTED",  "op", serial=1002)

        printed = audit.get_events_by_type("PRINTED", audit_db)
        assert len(printed) == 2
        assert all(e["event_type"] == "PRINTED" for e in printed)

    def test_events_ordered_oldest_first_for_serial(self, audit_db):
        audit.log_event(audit_db, "ALLOCATED", "op", serial=1001)
        audit.log_event(audit_db, "PRINTED",   "op", serial=1001)
        events = audit.get_events_for_serial(1001, audit_db)
        assert events[0]["event_type"] == "ALLOCATED"
        assert events[1]["event_type"] == "PRINTED"
