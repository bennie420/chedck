"""
test_amounts.py — Tests for src/amounts.py

Covers cents_to_courtesy(), cents_to_legal(), cents_to_display(),
and parse_amount_string() with a full sweep of edge-case amounts.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from amounts import cents_to_courtesy, cents_to_legal, cents_to_display, parse_amount_string


class TestCentsToCourtesy:
    def test_one_cent(self):
        result = cents_to_courtesy(1)
        assert result.endswith("$0.01")
        assert result.startswith("*")  # Fill characters present

    def test_one_dollar(self):
        result = cents_to_courtesy(100)
        assert "$1.00" in result

    def test_typical_amount(self):
        result = cents_to_courtesy(125000)  # $1,250.00
        assert "$1,250.00" in result
        # Fill characters should be present
        assert result.startswith("*")

    def test_large_amount(self):
        result = cents_to_courtesy(999999999)  # $9,999,999.99
        assert "$9,999,999.99" in result

    def test_zero_rejected(self):
        with pytest.raises(ValueError):
            cents_to_courtesy(0)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            cents_to_courtesy(-1)

    def test_fill_char_prevents_prepend(self):
        """The fill character must appear before the dollar sign."""
        result = cents_to_courtesy(100)
        dollar_idx = result.index("$")
        fill_portion = result[:dollar_idx]
        assert all(c == "*" for c in fill_portion), (
            f"Expected only fill chars before $, got: {fill_portion!r}"
        )

    def test_minimum_two_fill_chars(self):
        """At least 2 fill characters must precede the dollar amount."""
        # $9,999,999.99 is 12 chars; total_width = max(14, 10) = 14 → 2 fill chars
        result = cents_to_courtesy(999999999)
        dollar_idx = result.index("$")
        assert dollar_idx >= 2, (
            f"Expected at least 2 fill chars, got {dollar_idx}: {result!r}"
        )

    def test_comma_formatting(self):
        result = cents_to_courtesy(1000000)  # $10,000.00
        assert "$10,000.00" in result


class TestCentsToLegal:
    CASES = [
        (1,         "Zero Dollars",   False),  # special: 0 dollars, 1 cent
        (1,         "01/100",         True),
        (100,       "One",            True),
        (100,       "00/100",         True),
        (101,       "One",            True),
        (101,       "01/100",         True),
        (1099,      "Ten and 99/100", True),
        (125000,    "One Thousand Two Hundred Fifty", True),
        (125000,    "00/100",         True),
        (100000000, "One Million",    True),
        (999999,    "Nine Thousand Nine Hundred Ninety-Nine", True),
    ]

    def test_one_cent(self):
        result = cents_to_legal(1)
        assert "01/100" in result

    def test_one_dollar(self):
        result = cents_to_legal(100)
        assert "One" in result
        assert "00/100" in result

    def test_one_dollar_one_cent(self):
        result = cents_to_legal(101)
        assert "One" in result
        assert "01/100" in result

    def test_typical_amount(self):
        result = cents_to_legal(125000)  # $1,250.00
        assert "One Thousand Two Hundred Fifty" in result
        assert "00/100" in result

    def test_large_amount(self):
        result = cents_to_legal(100000000)  # $1,000,000.00
        assert "One Million" in result

    def test_trailing_fill_asterisks(self):
        result = cents_to_legal(100)  # Short text, should have fill
        assert "*" in result, f"Expected asterisk fill, got: {result!r}"

    def test_fill_reaches_line_width(self):
        """The total length should equal line_width when text is shorter."""
        for amt in [100, 12500, 125000]:
            result = cents_to_legal(amt, line_width=60)
            assert len(result) == 60, (
                f"Expected len 60 for amount {amt}, got {len(result)}: {result!r}"
            )

    def test_zero_rejected(self):
        with pytest.raises(ValueError):
            cents_to_legal(0)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            cents_to_legal(-100)

    def test_nineteen_dollars(self):
        result = cents_to_legal(1900)
        assert "Nineteen" in result

    def test_twenty_dollars(self):
        result = cents_to_legal(2000)
        assert "Twenty" in result

    def test_twenty_one_dollars(self):
        result = cents_to_legal(2100)
        assert "Twenty-One" in result

    def test_hundred_dollars(self):
        result = cents_to_legal(10000)
        assert "One Hundred" in result

    def test_both_derived_from_same_amount(self):
        """cents_to_display returns both; they must reflect the same amount."""
        courtesy, legal = cents_to_display(125050)  # $1,250.50
        assert "1,250.50" in courtesy
        assert "50/100" in legal


class TestParseAmountString:
    def test_plain_decimal(self):
        assert parse_amount_string("1250.00") == 125000

    def test_with_dollar_sign(self):
        assert parse_amount_string("$1,250.00") == 125000

    def test_with_commas(self):
        assert parse_amount_string("1,250.00") == 125000

    def test_one_cent(self):
        assert parse_amount_string("0.01") == 1

    def test_no_cents(self):
        assert parse_amount_string("100") == 10000

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            parse_amount_string("not-a-number")
