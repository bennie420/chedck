"""
micr.py — ANSI X9.100-160-1 / ANSI X9.27 E-13B MICR code-line builder.

Constructs the full 65-position MICR code line per ANSI ASC X9.100-160-1,
Federal Reserve Reg CC, Check 21 standards, and bank_config specifications.

Position numbering (ANSI standard):
  - Position 1  = LEADING / RIGHT edge of the check (0.3125" from right edge)
  - Position 65 = TRAILING / LEFT edge of the check

Print order on the face of the check (LEFT to RIGHT):
  - The printed code line starts on the left (position 65, index 0 of string)
  - and ends on the right (position 1, index 64 of string).
  - Index i (0 to 64) corresponds to position (65 - i).
  - Digits within all fields are printed in natural FORWARD left-to-right order.

Field Layouts:
  1. Personal Check (ANSI X9.100-160-1 Personal Specification):
     - Positions 45–65: BLANK (no Auxiliary On-Us on personal checks).
     - Positions 33–43: Transit field: ⑆[9-digit Routing]⑆
     - Positions 14–31: On-Us field: [Account Number]⑈ [Serial Number]⑈
     - Positions 1–12:  Amount field (blank on issue items).

  2. Business Check (ANSI X9.100-160-1 Business Specification):
     - Positions 45–65: Auxiliary On-Us: ⑈[Serial Number]⑈
     - Position 44:     EPC field (External Processing Code, optional).
     - Positions 33–43: Transit field: ⑆[9-digit Routing]⑆
     - Positions 14–31: On-Us field: [Account Number]⑈
     - Positions 1–12:  Amount field (blank on issue items).

E-13B special character Unicode mapping:
  ⑆  U+2446  Transit symbol       (⑆) — wraps routing/transit number
  ⑈  U+2448  On-Us symbol         (⑈) — wraps account, serial, Aux On-Us
  ⑇  U+2447  Amount symbol        (⑇) — wraps amount field (blank on issue)
  ⑉  U+2449  Dash symbol          (⑉) — used internally within On-Us when specified
"""

# ---------------------------------------------------------------------------
# E-13B symbol constants (Unicode code points)
# ---------------------------------------------------------------------------

TRANSIT = "\u2446"   # ⑆  transit/routing delimiter
ON_US   = "\u2448"   # ⑈  On-Us / account / serial delimiter
AMOUNT  = "\u2447"   # ⑇  amount field delimiter (not printed on issue items)
DASH    = "\u2449"   # ⑉  dash (used within On-Us when specified)

# Valid characters include both standard and legacy Unicode On-Us/Amount codepoints
VALID_MICR_CHARS = set("0123456789") | {TRANSIT, ON_US, AMOUNT, DASH, " ", "\u2447", "\u2448"}


# ---------------------------------------------------------------------------
# Code-line builder
# ---------------------------------------------------------------------------

def build_code_line(
    check: dict,
    bank_config: dict,
    check_type: str = "personal",
) -> str:
    """
    Build the 65-character MICR code line for the given check record,
    using ANSI X9.100-160-1 field boundaries.

    ``check`` must contain:
        routing_number  str(9)   — nine-digit ABA routing number
        account_number  str      — account number (digits only)
        serial_number   int      — check serial number

    ``check_type`` or ``check['layout']``:
        'personal' (default)     — Personal check format (Serial in On-Us)
        'business' / 'remittance'— Business check format (Serial in Aux On-Us)

    Returns a string of exactly 65 characters in LEFT-TO-RIGHT print order
    (as it appears on the face of the check).
    """
    routing = str(check["routing_number"]).strip()
    account = str(check["account_number"]).strip()
    raw_serial = check["serial_number"]
    fields = bank_config.get("micr_fields", {})

    raw_layout = check.get("layout")
    if raw_layout:
        layout = str(raw_layout).lower()
        is_business = (
            layout in ("business", "standard_business", "corporate", "remittance")
            or check.get("is_business", False)
        )
    else:
        is_business = (
            check.get("is_business", False)
            or check_type in ("business", "remittance")
            or "auxiliary_on_us" in fields
        )
    pad = check.get("serial_padding") or fields.get("auxiliary_on_us", {}).get("zero_pad", 0)
    if pad:
        serial = str(raw_serial).zfill(pad)
    else:
        serial = str(raw_serial)

    # 65-character print array (index 0 = leftmost / position 65, index 64 = rightmost / position 1)
    chars = [" "] * 65

    def _set_pos(position: int, char: str) -> None:
        """Write one character at a 1-indexed ANSI position (1 = rightmost, 65 = leftmost)."""
        if not (1 <= position <= 65):
            raise ValueError(f"Position {position} is outside 1–65")
        chars[65 - position] = char

    def _set_range(start: int, end: int, text: str, right_justify: bool = True) -> None:
        """
        Write ``text`` into positions start..end (inclusive, 1-indexed).
        Text is placed in natural left-to-right order (start = rightmost, end = leftmost).
        """
        field_len = end - start + 1
        if len(text) > field_len:
            raise ValueError(
                f"Text {text!r} ({len(text)} chars) is too long for "
                f"positions {start}–{end} ({field_len} chars)"
            )
        if right_justify:
            padded = text.rjust(field_len)
        else:
            padded = text.ljust(field_len)

        # In print space, 'end' is leftmost (index 65 - end)
        for i, ch in enumerate(padded):
            chars[65 - end + i] = ch

    # ------------------------------------------------------------------
    # Positions 33–43: Routing / Transit Field
    # Left transit at position 43 (print index 22)
    # 9 routing digits in positions 42 down to 34 (print indices 23..31)
    # Right transit at position 33 (print index 32)
    # ------------------------------------------------------------------
    rt_cfg = fields.get("routing_field", {"start": 33, "end": 43})
    rt_start = rt_cfg.get("start", 33)
    rt_end   = rt_cfg.get("end", 43)

    _set_pos(rt_end, TRANSIT)
    _set_range(rt_start + 1, rt_end - 1, routing, right_justify=True)
    _set_pos(rt_start, TRANSIT)

    # ------------------------------------------------------------------
    # Personal vs Business Layout
    # ------------------------------------------------------------------
    if is_business:
        # Positions 45–65: Auxiliary On-Us (Business check serial number)
        aux_cfg = fields.get("auxiliary_on_us", {"start": 45, "end": 65})
        aux_start = aux_cfg.get("start", 45)
        aux_end   = aux_cfg.get("end", 65)

        if aux_cfg.get("tight_delimiters", False):
            right_pos = aux_cfg.get("serial_rightmost_position", aux_start)
            left_pos  = right_pos + len(serial) + 1
            _set_pos(left_pos, ON_US)
            _set_range(right_pos + 1, left_pos - 1, serial, right_justify=False)
            _set_pos(right_pos, ON_US)
        else:
            # Enclose serial in On-Us symbols: left at aux_end (or serial_leftmost), right at aux_start
            left_pos = aux_cfg.get("serial_leftmost_position", aux_end)
            right_pos = aux_cfg.get("serial_rightmost_position", aux_start)
            _set_pos(left_pos, ON_US)
            _set_range(right_pos + 1, left_pos - 1, serial, right_justify=True)
            _set_pos(right_pos, ON_US)

        # Position 44: EPC (External Processing Code) — optional
        epc_cfg = fields.get("epc_field", {"position": 44, "use": False, "value": ""})
        if epc_cfg.get("use") and epc_cfg.get("value"):
            _set_pos(epc_cfg["position"], str(epc_cfg["value"])[0])

        # Positions 14–31: Business On-Us field (account number)
        on_us_cfg = fields.get("on_us_field", {"start": 14, "end": 31})
        on_start = on_us_cfg.get("start", 14)
        on_end   = on_us_cfg.get("end", 31)

        # Account digits followed by closing On-Us delimiter
        _set_range(on_start, on_end, account, right_justify=True)
        sep_pos = fields.get("on_us_separator", {}).get("position", on_start - 1 if on_start > 1 else 13)
        _set_pos(sep_pos, ON_US)

    else:
        # --------------------------------------------------------------
        # Personal Check: Positions 45–65 are blank per BofA Page 3 spec.
        # Routing Transit: positions 33–43 (⑆routing⑆)
        # On-Us Account: positions 19–31 (account⑈)
        # Check Serial: positions 13–17 (serial)
        # Positions 1–12: blank (Amount field)
        # --------------------------------------------------------------
        acct_str = f"{account}{ON_US}"
        _set_range(19, 31, acct_str, right_justify=True)
        _set_range(13, 17, serial[-5:], right_justify=True)

    # Validate characters
    for i, ch in enumerate(chars):
        if ch not in VALID_MICR_CHARS:
            raise ValueError(
                f"Illegal MICR character {ch!r} at print index {i} in code line"
            )

    code_line = "".join(chars)
    if len(code_line) != 65:
        raise AssertionError(f"Code line length is {len(code_line)}, expected 65")

    return code_line


# ---------------------------------------------------------------------------
# Utility: validate a completed code line string
# ---------------------------------------------------------------------------

def validate_code_line(code_line: str) -> list[str]:
    """
    Check a finished 65-character code line for common defects.
    Returns a list of warning strings (empty = clean).
    """
    warnings = []

    if len(code_line) != 65:
        warnings.append(f"Code line is {len(code_line)} chars, expected 65")

    for i, ch in enumerate(code_line):
        if ch not in VALID_MICR_CHARS:
            warnings.append(f"Illegal character {ch!r} at print index {i}")

    # Amount field (positions 1-12, rightmost 12 characters) must be blank
    amount_section = code_line[-12:]
    if amount_section.strip():
        warnings.append(
            f"Amount field (positions 1-12) should be blank on issue items, "
            f"found: {amount_section!r}"
        )

    return warnings
