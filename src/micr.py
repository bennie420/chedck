"""
micr.py — E-13B MICR code-line builder.

Constructs the full 65-position MICR code line per X9.100-160-1 and the
bank's field map in bank_config.json.

Position numbering (buildspec.md §4.1):
  - Position 1  = RIGHT/LEADING edge of the check
  - Position 65 = LEFT/TRAILING edge of the check

Internal representation uses a Python list indexed 0–64, where index 0
corresponds to position 1 (leading edge). The final string is constructed
left-to-right, meaning index 64 prints on the left and index 0 on the right.

Wait — actually: the code line is *read* right-to-left by the reader/sorter,
but it is *printed* left-to-right on the face (left edge = trailing = position
65, right edge = leading = position 1).

To place characters correctly in a left-to-right print system:
  - The MICR string we pass to ReportLab is ordered LEFT-TO-RIGHT on page.
  - Position 65 (trailing edge, left) is index 0 of the printed string.
  - Position 1  (leading edge, right) is index 64 of the printed string.

This module returns the string in LEFT-TO-RIGHT print order (as it appears
on the face of the check, readable when holding the check normally).

E-13B special character Unicode mapping (used by standard E-13B fonts):
  ⑆  U+2446  Transit symbol       (⑆) — wraps routing/transit number
  ⑈  U+2448  Amount symbol        (⑈) — wraps amount field (blank on issue)
  ⑇  U+2447  On-Us symbol         (⑇) — wraps On-Us and Aux On-Us fields
  ⑉  U+2449  Dash symbol          (⑉) — used within On-Us when needed

See buildspec.md §4.1 and §4.2.
"""


# ---------------------------------------------------------------------------
# E-13B symbol constants (Unicode code points)
# ---------------------------------------------------------------------------

TRANSIT = "\u2446"   # ⑆  transit/routing delimiter
AMOUNT  = "\u2448"   # ⑈  amount field delimiter (not printed on issue items)
ON_US   = "\u2447"   # ⑇  On-Us / account / serial delimiter
DASH    = "\u2449"   # ⑉  dash (used internally within On-Us when specified)

VALID_MICR_CHARS = set("0123456789") | {TRANSIT, AMOUNT, ON_US, DASH, " "}


# ---------------------------------------------------------------------------
# Code-line builder
# ---------------------------------------------------------------------------

def build_code_line(
    check: dict,
    bank_config: dict,
) -> str:
    """
    Build the 65-character MICR code line for the given check record,
    using the field map in bank_config.

    ``check`` must contain:
        routing_number  str(9)   — nine-digit ABA routing number
        account_number  str      — account number (digits only)
        serial_number   int      — check serial number

    Returns a string of exactly 65 characters in LEFT-TO-RIGHT print order
    (i.e. as it will appear on the face of the check).

    Raises ValueError if routing, account, or serial cannot fit into the
    configured field boundaries.
    """
    routing = check["routing_number"]
    account = check["account_number"]
    fields  = bank_config.get("micr_fields", {})

    pad = check.get("serial_padding") or fields.get("auxiliary_on_us", {}).get("zero_pad", 0)
    if pad:
        serial = str(check["serial_number"]).zfill(pad)
    else:
        serial = str(check["serial_number"])

    # Build positions array: index 0 = position 1 (leading/right edge).
    # We fill it LEFT-TO-RIGHT in position space, then reverse for printing.
    # Array of 65 blanks.
    pos = [" "] * 65  # index i → position (i+1)

    def _set_pos(position: int, char: str) -> None:
        """Write one character at a 1-indexed position."""
        if not (1 <= position <= 65):
            raise ValueError(f"Position {position} is outside 1–65")
        pos[position - 1] = char

    def _set_range(start: int, end: int, text: str, right_justify: bool = True) -> None:
        """
        Write ``text`` into positions start..end (inclusive, 1-indexed).
        Text is right-justified within the field (unused left positions = blank).
        Raises if text is longer than the field.
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
        for i, ch in enumerate(padded):
            _set_pos(start + i, ch)

    # ------------------------------------------------------------------
    # Positions 1–12: Amount field (left blank on issue items — the bank
    # of first deposit encodes it).  Buildspec §4.2.
    # ------------------------------------------------------------------
    # Leave positions 1–12 as blank spaces.

    # ------------------------------------------------------------------
    # Position 13: Amount field separator (blank).
    # ------------------------------------------------------------------
    # Leave blank.

    # ------------------------------------------------------------------
    # Positions 14–31: On-Us field (account number, right-justified).
    # Standard layout: [On-Us symbol][digits right-justified][blank]
    # ------------------------------------------------------------------
    on_us_cfg   = fields.get("on_us_field", {"start": 14, "end": 31})
    on_us_start = on_us_cfg["start"]
    on_us_end   = on_us_cfg["end"]

    # On-Us symbol to the left of the digit field (optional, default True).
    if on_us_cfg.get("left_delimiter", True):
        _set_pos(on_us_start, ON_US)
        _set_range(on_us_start + 1, on_us_end, account, right_justify=True)
    else:
        _set_range(on_us_start, on_us_end, account, right_justify=True)

    # On-Us symbol to the right of the digit field (closing delimiter).
    sep_pos = fields.get("on_us_separator", {}).get("position", 32)
    _set_pos(sep_pos, ON_US)

    # ------------------------------------------------------------------
    # Positions 33–43: Routing/transit field.
    # Transit symbols at the leftmost and rightmost positions; nine routing
    # digits in the middle.
    # Standard: [transit][9 digits][transit]
    # positions 33 = left transit, 34–42 = 9 digits, 43 = right transit.
    # ------------------------------------------------------------------
    rt_cfg   = fields.get("routing_field", {"start": 33, "end": 43})
    rt_start = rt_cfg["start"]
    rt_end   = rt_cfg["end"]

    _set_pos(rt_start, TRANSIT)
    _set_range(rt_start + 1, rt_end - 1, routing)
    _set_pos(rt_end, TRANSIT)

    # ------------------------------------------------------------------
    # Position 44: EPC (External Processing Code) — optional.
    # Leave blank unless bank_config instructs otherwise.
    # ------------------------------------------------------------------
    epc_cfg = fields.get("epc_field", {"position": 44, "use": False, "value": ""})
    if epc_cfg.get("use") and epc_cfg.get("value"):
        epc_pos = epc_cfg["position"]
        _set_pos(epc_pos, str(epc_cfg["value"])[0])

    # ------------------------------------------------------------------
    # Positions 45–65: Auxiliary On-Us (check serial number).
    # Business checks only.  Serial number bounded by On-Us symbols.
    # ------------------------------------------------------------------
    aux_cfg = fields.get("auxiliary_on_us", {"start": 45, "end": 65})
    aux_start = aux_cfg.get("start", 45)
    aux_end   = aux_cfg.get("end", 65)

    if aux_cfg.get("tight_delimiters", False):
        right_pos = aux_cfg.get("serial_rightmost_position", aux_start)
        left_pos  = right_pos + len(serial) + 1
        _set_pos(right_pos, ON_US)
        _set_range(right_pos + 1, left_pos - 1, serial, right_justify=False)
        _set_pos(left_pos, ON_US)
    else:
        # Left On-Us symbol
        _set_pos(aux_start, ON_US)
        # Serial number, right-justified in the digit range aux_start+1 .. aux_end-1
        _set_range(aux_start + 1, aux_end - 1, serial, right_justify=True)
        # Right On-Us symbol
        _set_pos(aux_end, ON_US)

    # ------------------------------------------------------------------
    # Validate: only legal MICR characters in the final line.
    # ------------------------------------------------------------------
    for i, ch in enumerate(pos):
        if ch not in VALID_MICR_CHARS:
            raise ValueError(
                f"Illegal MICR character {ch!r} at position {i+1} in code line"
            )

    # ------------------------------------------------------------------
    # Build the print string.
    # The pos[] array is indexed 0 = position 1 (leading/right edge).
    # Printed left-to-right on the face: position 65 prints leftmost.
    # Reverse the array to get left-to-right print order.
    # ------------------------------------------------------------------
    print_string = "".join(reversed(pos))

    if len(print_string) != 65:
        raise AssertionError(
            f"Code line length is {len(print_string)}, expected 65"
        )

    return print_string


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

    # The amount field (positions 1-12, which are the LAST 12 chars of the
    # print string in left-to-right order) should be blank on an issue item.
    # In print order (L→R), positions 1-12 are the rightmost 12 characters.
    amount_section = code_line[-12:]
    if amount_section.strip():
        warnings.append(
            f"Amount field (positions 1-12) should be blank on issue items, "
            f"found: {amount_section!r}"
        )

    return warnings
