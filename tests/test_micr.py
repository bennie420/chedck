"""
test_micr.py — Tests for src/micr.py

Verifies the 65-position MICR code line structure per ANSI X9.100-160-1,
testing both Personal Check and Business Check layouts.
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
        # In print order, position 43 (left transit) is at index 65-43 = 22.
        # Position 33 (right transit) is at index 65-33 = 32.
        pos43_idx = 65 - 43  # = 22
        pos33_idx = 65 - 33  # = 32

        assert line[pos43_idx] == TRANSIT, (
            f"Expected TRANSIT at print index {pos43_idx} (position 43), "
            f"got {line[pos43_idx]!r}"
        )
        assert line[pos33_idx] == TRANSIT, (
            f"Expected TRANSIT at print index {pos33_idx} (position 33), "
            f"got {line[pos33_idx]!r}"
        )

    def test_routing_digits_embedded_forward(self):
        """Routing digits must be printed forward, left-to-right (not reversed)."""
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        # In forward print order, indices 23 to 31 (positions 42 down to 34) are the 9 routing digits.
        routing_section = line[23:32]
        expected = SAMPLE_CHECK["routing_number"]
        assert routing_section == expected, (
            f"Expected forward routing {expected!r} at indices 23..31, "
            f"got {routing_section!r}\nFull line: {line!r}"
        )


class TestOnUsField:
    """Account number must appear in forward order in the On-Us field."""

    def test_account_in_on_us(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        assert SAMPLE_CHECK["account_number"] in line, (
            f"Account number {SAMPLE_CHECK['account_number']!r} not found "
            f"in forward code line: {line!r}"
        )

    def test_on_us_symbol_present(self):
        line = build_code_line(SAMPLE_CHECK, BANK_CONFIG)
        assert ON_US in line, "On-Us symbol not found in code line"


class TestPersonalCheckLayout:
    """Personal check MICR codeline per ANSI X9.100-160-1 Personal Specification."""

    def test_aux_on_us_is_blank_on_personal_check(self):
        check = {**SAMPLE_CHECK, "layout": "personal"}
        line = build_code_line(check, BANK_CONFIG)
        # Positions 45-65 (print indices 0 to 20) must be completely blank
        aux_section = line[0:21]
        assert aux_section.strip() == "", (
            f"Aux On-Us positions 45-65 should be blank on personal check, got: {aux_section!r}"
        )

    def test_serial_in_on_us_on_personal_check(self):
        check = {**SAMPLE_CHECK, "layout": "personal", "serial_number": 1042}
        line = build_code_line(check, BANK_CONFIG)
        assert "1042" in line, f"Serial 1042 not found in personal code line: {line!r}"
        # Make sure routing is also present
        assert "021000021" in line
        assert "123456789" in line


class TestBusinessCheckLayout:
    """Business check MICR codeline per ANSI X9.100-160-1 Business Specification."""

    def test_serial_in_aux_on_us(self):
        check = {**SAMPLE_CHECK, "layout": "business"}
        line = build_code_line(check, BANK_CONFIG)
        assert str(SAMPLE_CHECK["serial_number"]) in line, (
            f"Serial {SAMPLE_CHECK['serial_number']} not found in business code line: {line!r}"
        )

    def test_serial_matches_digit_for_digit(self):
        check = {**SAMPLE_CHECK, "layout": "business", "serial_number": 9876}
        line = build_code_line(check, BANK_CONFIG)
        # Positions 45-65 (indices 0 to 20) contain Aux On-Us
        aux_section = line[0:21]
        assert "9876" in aux_section, f"Serial 9876 not found in Aux On-Us: {aux_section!r}"


class TestEPCField:
    """EPC field (position 44) must be blank when use=False."""

    def test_epc_blank_when_disabled(self):
        check = {**SAMPLE_CHECK, "layout": "business"}
        line = build_code_line(check, BANK_CONFIG)
        # Position 44 → print index = 65 - 44 = 21
        pos44_idx = 65 - 44  # = 21
        assert line[pos44_idx] == " ", (
            f"EPC field (position 44, print index {pos44_idx}) should be blank, "
            f"got {line[pos44_idx]!r}"
        )


class TestDifferentSerials:
    """Different serial numbers should produce different code lines."""

    def test_different_serials_produce_different_lines(self):
        check1 = {**SAMPLE_CHECK, "serial_number": 1001, "layout": "personal"}
        check2 = {**SAMPLE_CHECK, "serial_number": 1002, "layout": "personal"}
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
        illegal = [w for w in warnings if "Illegal" in w]
        assert not illegal

    def test_wrong_length_flagged(self):
        warnings = validate_code_line("x" * 64)
        assert any("65" in w for w in warnings)
