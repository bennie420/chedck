"""
test_validation.py — Tests for src/validation.py

Covers routing number mod-10 (buildspec.md §4.3), account number field
boundaries, amount validation, and payee name validation.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from validation import (
    validate_routing_number,
    validate_account_number,
    validate_amount_cents,
    validate_payee_name,
    validate_serial_number,
    validate_fractional_routing,
)


# ---------------------------------------------------------------------------
# Routing number
# ---------------------------------------------------------------------------

class TestRoutingNumber:
    """Known-good routing numbers (publicly documented ABA numbers)."""

    KNOWN_GOOD = [
        "021000021",  # JPMorgan Chase
        "021200339",  # Citibank NY
        "122105155",  # Wells Fargo CA
        "026009593",  # Bank of America
        "011401533",  # Sovereign (Santander)
        "091000022",  # US Bancorp
        "267084131",  # Bank of America FL
        "063100277",  # JPMorgan Chase FL
    ]

    def test_known_good_routing_numbers(self):
        for rt in self.KNOWN_GOOD:
            assert validate_routing_number(rt) is True, f"Should pass: {rt}"

    def test_known_bad_check_digit(self):
        """Incrementing the last digit by 1 breaks the checksum."""
        bad = [
            "021000022",
            "021200330",
            "122105156",
        ]
        for rt in bad:
            with pytest.raises(ValueError, match="mod-10"):
                validate_routing_number(rt)

    def test_all_zeros_rejected(self):
        with pytest.raises(ValueError, match="placeholder"):
            validate_routing_number("000000000")

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="exactly 9 digits"):
            validate_routing_number("12345678")

    def test_non_digits(self):
        with pytest.raises(ValueError, match="exactly 9 digits"):
            validate_routing_number("02100002A")

    def test_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_routing_number(21000021)

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped before validation."""
        assert validate_routing_number(" 021000021 ") is True

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_routing_number("")


# ---------------------------------------------------------------------------
# Account number
# ---------------------------------------------------------------------------

class TestAccountNumber:
    BANK_CONFIG = {
        "micr_fields": {
            "on_us_field": {"start": 14, "end": 31}
        }
    }

    def test_valid_account(self):
        assert validate_account_number("123456789", self.BANK_CONFIG) is True

    def test_max_length_accepted(self):
        # On-Us field 14-31 = 18 positions; position 14 = On-Us symbol → 17 digits max
        # Our validator checks: field len = 31-14+1 = 18.
        assert validate_account_number("1" * 18, self.BANK_CONFIG) is True

    def test_too_long(self):
        with pytest.raises(ValueError, match="allows at most"):
            validate_account_number("1" * 19, self.BANK_CONFIG)

    def test_non_digits(self):
        with pytest.raises(ValueError, match="only digits"):
            validate_account_number("1234A6789", self.BANK_CONFIG)

    def test_empty(self):
        with pytest.raises(ValueError, match="not be empty"):
            validate_account_number("", self.BANK_CONFIG)

    def test_all_zeros_rejected(self):
        with pytest.raises(ValueError, match="actual account number"):
            validate_account_number("000000000", self.BANK_CONFIG)


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------

class TestAmountCents:
    def test_one_cent(self):
        assert validate_amount_cents(1) is True

    def test_typical_amounts(self):
        for amt in [100, 12500, 999999, 1_000_000]:
            assert validate_amount_cents(amt) is True

    def test_zero_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            validate_amount_cents(0)

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            validate_amount_cents(-1)

    def test_float_rejected(self):
        with pytest.raises(ValueError, match="never a float"):
            validate_amount_cents(12.50)

    def test_non_int_rejected(self):
        with pytest.raises(ValueError, match="must be an int"):
            validate_amount_cents("1250")

    def test_over_max_rejected(self):
        with pytest.raises(ValueError, match="maximum"):
            validate_amount_cents(1_000_000_000)


# ---------------------------------------------------------------------------
# Payee name
# ---------------------------------------------------------------------------

class TestPayeeName:
    def test_normal_payee(self):
        assert validate_payee_name("Acme Corporation") is True

    def test_short_payee(self):
        assert validate_payee_name("A") is True

    def test_max_length_accepted(self):
        assert validate_payee_name("X" * 70) is True

    def test_too_long_rejected(self):
        with pytest.raises(ValueError, match="70"):
            validate_payee_name("X" * 71)

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="not be empty"):
            validate_payee_name("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="not be empty"):
            validate_payee_name("   ")

    def test_control_chars_rejected(self):
        with pytest.raises(ValueError, match="control characters"):
            validate_payee_name("Acme\x00Corp")


# ---------------------------------------------------------------------------
# Serial number
# ---------------------------------------------------------------------------

class TestSerialNumber:
    def test_valid_serials(self):
        for s in [1, 1001, 9999, 9_999_999_999]:
            assert validate_serial_number(s) is True

    def test_zero_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            validate_serial_number(0)

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            validate_serial_number(-1)

    def test_too_large_rejected(self):
        with pytest.raises(ValueError, match="10 digits"):
            validate_serial_number(10_000_000_000)

    def test_float_rejected(self):
        with pytest.raises(ValueError, match="must be an int"):
            validate_serial_number(1.0)


# ---------------------------------------------------------------------------
# Fractional routing
# ---------------------------------------------------------------------------

class TestFractionalRouting:
    def test_valid_format(self):
        assert validate_fractional_routing("70-2322/719") is True

    def test_placeholder_rejected(self):
        with pytest.raises(ValueError, match="placeholder"):
            validate_fractional_routing("00-0000/000")

    def test_bad_format(self):
        with pytest.raises(ValueError, match="format"):
            validate_fractional_routing("70-2322719")

    def test_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_fractional_routing(70)
