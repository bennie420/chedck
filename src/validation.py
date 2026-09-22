"""
validation.py — Input validation for the check printing system.

Implements:
  - ABA routing number mod-10 check digit (buildspec.md §4.3)
  - Account number field-boundary validation (buildspec.md §4.2)
  - Amount, payee, and serial validation

All functions raise ValueError with a human-readable message on failure,
or return True on success, so callers can decide whether to raise or log.
"""

import re


# ---------------------------------------------------------------------------
# Routing number
# ---------------------------------------------------------------------------

def validate_routing_number(routing: str) -> bool:
    """
    Validate a 9-digit ABA routing/transit number using the mod-10 formula
    from buildspec.md §4.3:

        (3*(d1+d4+d7) + 7*(d2+d5+d8) + 1*(d3+d6+d9)) mod 10 == 0

    Raises ValueError on any failure; returns True on success.
    """
    if not isinstance(routing, str):
        raise ValueError(f"Routing number must be a string, got {type(routing).__name__}")

    routing = routing.strip()

    if not re.fullmatch(r"\d{9}", routing):
        raise ValueError(
            f"Routing number must be exactly 9 digits, got: {routing!r}"
        )

    d = [int(c) for c in routing]
    checksum = (
        3 * (d[0] + d[3] + d[6])
        + 7 * (d[1] + d[4] + d[7])
        + 1 * (d[2] + d[5] + d[8])
    )
    if checksum % 10 != 0:
        raise ValueError(
            f"Routing number {routing!r} fails the mod-10 check digit test "
            f"(checksum={checksum}, remainder={checksum % 10})"
        )

    # All-zeros is technically valid mod-10 but is not a real routing number.
    if routing == "000000000":
        raise ValueError(
            "Routing number 000000000 is a placeholder — replace with your "
            "actual ABA routing number in config/account_config.json"
        )

    return True


# ---------------------------------------------------------------------------
# Account number
# ---------------------------------------------------------------------------

def validate_account_number(account: str, bank_config: dict) -> bool:
    """
    Validate that the account number fits within the On-Us field boundaries
    defined in bank_config (positions 14-31 by default, 18 characters max).

    Raises ValueError on failure; returns True on success.
    """
    if not isinstance(account, str):
        raise ValueError(f"Account number must be a string, got {type(account).__name__}")

    account = account.strip()

    if not account:
        raise ValueError("Account number must not be empty")

    if not re.fullmatch(r"\d+", account):
        raise ValueError(
            f"Account number must contain only digits, got: {account!r}"
        )

    on_us = bank_config.get("micr_fields", {}).get("on_us_field", {})
    start = on_us.get("start", 14)
    end = on_us.get("end", 31)
    max_len = end - start + 1  # e.g. 31-14+1 = 18

    if len(account) > max_len:
        raise ValueError(
            f"Account number {account!r} is {len(account)} digits but the "
            f"On-Us field (positions {start}-{end}) allows at most {max_len} digits"
        )

    if account == "0" * len(account):
        raise ValueError(
            "Account number is all zeros — replace with your actual account number "
            "in config/account_config.json"
        )

    return True


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------

def validate_amount_cents(amount_cents: int) -> bool:
    """
    Validate a payment amount expressed in cents.

    Rules:
      - Must be a plain int (not float — floats are forbidden for money).
      - Must be positive (> 0).
      - Must be representable in the check courtesy-amount box (≤ $9,999,999.99).

    Raises ValueError on failure; returns True on success.
    """
    if isinstance(amount_cents, float):
        raise ValueError(
            "amount_cents must be an integer (never a float). "
            "Convert dollars to cents as int(round(dollars * 100))."
        )

    if not isinstance(amount_cents, int):
        raise ValueError(
            f"amount_cents must be an int, got {type(amount_cents).__name__}"
        )

    if amount_cents <= 0:
        raise ValueError(
            f"amount_cents must be positive (> 0), got {amount_cents}"
        )

    max_cents = 999_999_999  # $9,999,999.99
    if amount_cents > max_cents:
        raise ValueError(
            f"amount_cents {amount_cents} exceeds the maximum printable amount "
            f"({max_cents} = $9,999,999.99)"
        )

    return True


# ---------------------------------------------------------------------------
# Payee name
# ---------------------------------------------------------------------------

def validate_payee_name(payee: str) -> bool:
    """
    Validate the payee name.

    Rules:
      - Must be a non-empty string.
      - Max 70 characters (fits the payee line with reasonable font sizes).
      - Must not contain control characters.

    Raises ValueError on failure; returns True on success.
    """
    if not isinstance(payee, str):
        raise ValueError(f"Payee name must be a string, got {type(payee).__name__}")

    payee = payee.strip()

    if not payee:
        raise ValueError("Payee name must not be empty or whitespace-only")

    if len(payee) > 70:
        raise ValueError(
            f"Payee name is {len(payee)} characters; maximum is 70 "
            f"(value: {payee!r})"
        )

    if re.search(r"[\x00-\x1f\x7f]", payee):
        raise ValueError(
            f"Payee name contains control characters: {payee!r}"
        )

    return True


# ---------------------------------------------------------------------------
# Serial number
# ---------------------------------------------------------------------------

def validate_serial_number(serial: int) -> bool:
    """
    Validate a check serial number.

    Rules:
      - Must be a positive integer.
      - Must fit in the Auxiliary On-Us field (≤ 10 digits for the serial portion).

    Raises ValueError on failure; returns True on success.
    """
    if not isinstance(serial, int) or isinstance(serial, bool):
        raise ValueError(
            f"Serial number must be an int, got {type(serial).__name__}"
        )

    if serial <= 0:
        raise ValueError(f"Serial number must be positive (> 0), got {serial}")

    if serial > 9_999_999_999:
        raise ValueError(
            f"Serial number {serial} exceeds 10 digits and cannot fit in the "
            "Auxiliary On-Us field"
        )

    return True


# ---------------------------------------------------------------------------
# Fractional routing number
# ---------------------------------------------------------------------------

def validate_fractional_routing(frac: str) -> bool:
    """
    Validate the fractional routing number format: prefix-suffix/FRB.
    Example valid value: "70-2322/719"

    This is a loose structural check — the actual values come from your bank.
    Raises ValueError on failure; returns True on success.
    """
    if not isinstance(frac, str):
        raise ValueError(
            f"Fractional routing must be a string, got {type(frac).__name__}"
        )

    frac = frac.strip()

    if not re.fullmatch(r"\d+-\d+/\d+(?:\s+[A-Za-z]{2})?", frac):
        raise ValueError(
            f"Fractional routing number {frac!r} does not match the expected "
            "format 'prefix-suffix/FRB' (e.g. '70-2322/719' or '51-44/119 CT'). "
            "This is a placeholder — set the real value in config/account_config.json."
        )

    if frac == "00-0000/000":
        raise ValueError(
            "Fractional routing 00-0000/000 is a placeholder — set your real "
            "fractional routing number in config/account_config.json"
        )

    return True
