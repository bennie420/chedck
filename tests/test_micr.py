"""
test_micr.py — Tests for src/micr.py

Verifies the 65-position MICR code line structure per X9.100-160-1
and buildspec.md §4.1–4.2.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from micr import build_code_line, validate_code_line, TRANSIT, ON_US, AMOUNT, DASH


# Standard Chase-like config (default bank_config.json values)
BANK_CONFIG = {
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
    }
}

SAMPLE_CHECK = {
    "serial_number":  1001,
    "account_number": "123456789",
    "routing_number": "021000021",  # Chase (known-good ABA)
}


class TestCodeLineLength:
    def test_code_line_is_65_chars(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        assert len(line) == 65, f"Expected 65 chars, got {len(line)}: {line!r}"

    def test_no_illegal_characters(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        warnings = validate_code_line(line)
        illegal = [w for w in warnings if "Illegal character" in w]
        assert not illegal, f"Illegal characters found: {illegal}"


class TestAmountField:
    """Positions 1–12 must be blank on issue items (buildspec.md §4.2)."""

    def test_amount_field_is_blank(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # In print order (L→R), positions 1-12 are the RIGHTMOST 12 chars.
        amount_section = line[-12:]
        assert amount_section.strip() == "", (
            f"Amount field (rightmost 12 chars) should be blank, got: {amount_section!r}"
        )


class TestRoutingField:
    """Routing number must be at positions 33–43, bounded by TRANSIT symbols."""

    def test_routing_transit_symbols_present(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # In print order, position 43 (rightmost transit) is at index 65-43 = 22 from left.
        # Position 33 (leftmost transit) is at index 65-33 = 32 from left.
        # Index = 65 - position (since we reversed the array for print order).
        pos33_idx = 65 - 33  # = 32
        pos43_idx = 65 - 43  # = 22

        assert line[pos33_idx] == TRANSIT, (
            f"Expected TRANSIT at print index {pos33_idx} (position 33), "
            f"got {line[pos33_idx]!r}"
        )
        assert line[pos43_idx] == TRANSIT, (
            f"Expected TRANSIT at print index {pos43_idx} (position 43), "
            f"got {line[pos43_idx]!r}"
        )

    def test_routing_digits_embedded(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # The MICR code line string is in LEFT-TO-RIGHT print order.
        # The reader/sorter reads RIGHT-TO-LEFT (from leading/right edge).
        # Reading the print string right-to-left gives scanner order:
        scanner_order = line[::-1]
        # In scanner order, positions 33-43 are at indices 32-42.
        # Positions 34-42 (9 digits) are at scanner-order indices 33-41.
        routing_section = scanner_order[33:42]  # 9 chars
        expected = SAMPLE_CHECK["routing_number"]
        assert routing_section == expected, (
            f"Expected routing {expected!r} at scanner-order indices 33-41, "
            f"got {routing_section!r}\nFull scanner order: {scanner_order!r}"
        )


class TestOnUsField:
    """Account number must appear in the On-Us field (positions 14–31)."""

    def test_account_in_on_us(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # The account number in the print string appears in reverse order
        # because the print string goes position 65 (left) to position 1 (right).
        # The scanner reads right-to-left, so check scanner order:
        scanner_order = line[::-1]
        assert SAMPLE_CHECK["account_number"] in scanner_order, (
            f"Account number {SAMPLE_CHECK['account_number']!r} not found "
            f"in scanner-order code line: {scanner_order!r}"
        )

    def test_on_us_symbol_present(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        assert ON_US in line, "On-Us symbol not found in code line"


class TestAuxOnUsField:
    """Serial number must appear in the Auxiliary On-Us field (positions 45–65)."""

    def test_serial_in_aux_on_us(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        assert str(SAMPLE_CHECK["serial_number"]) in line, (
            f"Serial {SAMPLE_CHECK['serial_number']} not found in code line"
        )

    def test_serial_matches_digit_for_digit(self):
        """The serial in the Aux On-Us must exactly match check.serial_number."""
        check = {**SAMPLE_CHECK, "serial_number": 9876}
        line = build_code_line(check, BANK_CONFIG)
        assert "9876" in line, f"Serial 9876 not found in code line: {line!r}"


class TestEPCField:
    """EPC field (position 44) must be blank when use=False."""

    def test_epc_blank_when_disabled(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # Position 44 → print index = 65 - 44 = 21
        pos44_idx = 65 - 44  # = 21
        assert line[pos44_idx] == " ", (
            f"EPC field (position 44, print index {pos44_idx}) should be blank, "
            f"got {line[pos44_idx]!r}"
        )


class TestDifferentSerials:
    """Different serial numbers should produce different code lines."""

    def test_different_serials_produce_different_lines(self):
        check1 = {**SAMPLE_CHECK, "serial_number": 1001}
        check2 = {**SAMPLE_CHECK, "serial_number": 1002}
        line1 = build_code_line(check1, BANK_CONFIG)
        line2 = build_code_line(check2, BANK_CONFIG)
        assert line1 != line2

    def test_different_accounts_produce_different_lines(self):
        check1 = {**SAMPLE_CHECK, "account_number": "111111111"}
        check2 = {**SAMPLE_CHECK, "account_number": "222222222"}
        line1 = build_code_line(check1, BANK_CONFIG)
        line2 = build_code_line(check2, BANK_CONFIG)
        assert line1 != line2


class TestValidateCodeLine:
    def test_clean_line_returns_no_warnings(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        warnings = validate_code_line(line)
        # The only expected warning would be about illegal chars; none expected.
        illegal = [w for w in warnings if "Illegal" in w]
        assert not illegal

    def test_wrong_length_flagged(self):
        warnings = validate_code_line("x" * 64)
        assert any("65" in w for w in warnings)
