"""
test_pipeline_integration.py — End-to-end integration test.

Runs the full pipeline in TEST mode (PRODUCTION_LOCK != LIVE):
  - Payment request → PDF rendered → serial allocated → Positive Pay file
    generated → audit log written.

No actual printing occurs. All databases are temporary.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit
import sequence
from print_pipeline import run_pipeline, load_config

# Override config path to use test configs
TEST_CONFIG_DIR = Path(__file__).parent / "test_configs"


def _write_test_configs(config_dir: Path) -> None:
    """Write minimal valid test configs to a temp directory."""
    config_dir.mkdir(parents=True, exist_ok=True)

    bank_cfg = {
        "bank_name": "Test Bank N.A.",
        "bank_city_state": "Testville, TX",
        "micr_fields": {
            "amount_field":     {"start": 1,  "end": 12},
            "amount_separator": {"position": 13},
            "on_us_field":      {"start": 14, "end": 31},
            "on_us_separator":  {"position": 32},
            "routing_field":    {"start": 33, "end": 43},
            "epc_field":        {"position": 44, "use": False, "value": ""},
            "auxiliary_on_us":  {
                "start": 45, "end": 65,
                "serial_rightmost_position": 46,
                "serial_leftmost_position":  55,
            },
        },
        "positive_pay": {
            "format": "csv",
            "fields_order": ["account_number", "check_number", "issue_date",
                             "amount", "payee_name", "void_flag"],
            "date_format": "%m/%d/%Y",
        },
        "reconciliation": {
            "format": "csv",
            "csv_columns": {"serial": "CheckNumber", "cleared_date": "PostDate",
                            "amount": "Amount", "payee": "Description"},
        },
    }

    account_cfg = {
        "drawer_name": "Test LLC",
        "drawer_address": "1 Test Street",
        "drawer_city_state_zip": "Testville, TX 00001",
        "account_id": "primary",
        "account_number": "123456789",
        "routing_number": "021000021",  # Chase (valid mod-10)
        "fractional_routing": "70-2322/719",
        "check_dimensions": {"width_in": 8.5, "height_in": 3.5},
    }

    security_cfg = {
        "production_lock": "TEST",
        "signature_auto_threshold_cents": 500000,
        "dual_control_mode": False,
        "max_blank_stock_years": 1,
        "void_shred_required": True,
        "alert_unprotected_printed_checks": True,
    }

    (config_dir / "bank_config.json").write_text(json.dumps(bank_cfg))
    (config_dir / "account_config.json").write_text(json.dumps(account_cfg))
    (config_dir / "security_config.json").write_text(json.dumps(security_cfg))


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """
    Set up a complete isolated test environment with temp config, db, and output dirs.
    Patches the PROJECT_ROOT so load_config reads from our test configs.
    """
    config_dir = tmp_path / "config"
    _write_test_configs(config_dir)

    db_dir     = tmp_path / "db"
    output_dir = tmp_path / "output"

    # Patch the PROJECT_ROOT in print_pipeline to point at tmp_path
    import print_pipeline
    monkeypatch.setattr(print_pipeline, "PROJECT_ROOT", tmp_path)

    return {
        "config_dir": config_dir,
        "db_dir":     db_dir,
        "output_dir": output_dir,
        "tmp_path":   tmp_path,
    }


class TestFullPipeline:
    def test_pipeline_runs_in_test_mode(self, test_env):
        """Full pipeline should complete without error in TEST mode."""
        result = run_pipeline(
            payee="Acme Corporation",
            amount_cents=125000,
            issue_date="2026-09-19",
            memo="Invoice 12345",
            operator_id="test_operator",
            printer_id="TestPrinter",
            cartridge_serial="CART001",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )

        assert result["serial_number"] == 1001
        assert result["status"] == "printed"
        assert result["production_mode"] == "TEST"

    def test_pdf_is_created(self, test_env):
        """A PDF file should be generated in the output directory."""
        result = run_pipeline(
            payee="Acme Corporation",
            amount_cents=125000,
            issue_date="2026-09-19",
            memo="",
            operator_id="test_operator",
            printer_id="",
            cartridge_serial="",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )

        pdf_path = Path(result["pdf_path"])
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_serial_allocated_in_db(self, test_env):
        """The check record should appear in the database after the pipeline."""
        result = run_pipeline(
            payee="Vendor ABC",
            amount_cents=50000,
            issue_date="2026-09-19",
            memo="",
            operator_id="test_operator",
            printer_id="",
            cartridge_serial="",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )

        serial = result["serial_number"]
        checks_db = test_env["db_dir"] / "checks.db"
        conn = sequence.get_connection(checks_db)
        record = sequence.get_check_record(serial, conn)
        conn.close()

        assert record is not None
        assert record["payee_name"] == "Vendor ABC"
        assert record["amount_cents"] == 50000
        assert record["status"] == "printed"

    def test_positive_pay_file_generated(self, test_env):
        """A Positive Pay CSV file should appear in output/positive_pay/."""
        result = run_pipeline(
            payee="Acme Corporation",
            amount_cents=125000,
            issue_date="2026-09-19",
            memo="",
            operator_id="test_operator",
            printer_id="",
            cartridge_serial="",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )

        assert result["positive_pay_export_id"] is not None
        pp_dir = test_env["output_dir"] / "positive_pay"
        csv_files = list(pp_dir.glob("*.csv"))
        assert len(csv_files) > 0

    def test_audit_events_logged(self, test_env):
        """ALLOCATED and PRINTED events must be in the audit log."""
        result = run_pipeline(
            payee="Acme Corporation",
            amount_cents=125000,
            issue_date="2026-09-19",
            memo="",
            operator_id="test_operator",
            printer_id="",
            cartridge_serial="",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )

        audit_db_path = test_env["db_dir"] / "audit.db"
        audit_conn = audit.get_audit_connection(audit_db_path)
        serial = result["serial_number"]
        events = audit.get_events_for_serial(serial, audit_conn)
        audit_conn.close()

        event_types = [e["event_type"] for e in events]
        assert "ALLOCATED" in event_types
        assert "PRINTED" in event_types

    def test_sequential_serials(self, test_env):
        """Two consecutive pipeline runs should get sequential serial numbers."""
        common_args = dict(
            payee="Acme Corporation",
            amount_cents=125000,
            issue_date="2026-09-19",
            memo="",
            operator_id="test_operator",
            printer_id="",
            cartridge_serial="",
            output_dir=test_env["output_dir"],
            db_dir=test_env["db_dir"],
            vault_passphrase=None,
        )
        result1 = run_pipeline(**common_args)
        result2 = run_pipeline(**common_args)

        assert result2["serial_number"] == result1["serial_number"] + 1

    def test_invalid_payee_rejected(self, test_env):
        """Pipeline must reject an empty payee before any DB write."""
        with pytest.raises((ValueError, SystemExit)):
            run_pipeline(
                payee="",  # Invalid
                amount_cents=125000,
                issue_date="2026-09-19",
                memo="",
                operator_id="test_operator",
                printer_id="",
                cartridge_serial="",
                output_dir=test_env["output_dir"],
                db_dir=test_env["db_dir"],
                vault_passphrase=None,
            )

    def test_invalid_amount_rejected(self, test_env):
        """Pipeline must reject a zero amount."""
        with pytest.raises((ValueError, SystemExit)):
            run_pipeline(
                payee="Acme Corp",
                amount_cents=0,  # Invalid
                issue_date="2026-09-19",
                memo="",
                operator_id="test_operator",
                printer_id="",
                cartridge_serial="",
                output_dir=test_env["output_dir"],
                db_dir=test_env["db_dir"],
                vault_passphrase=None,
            )
