"""
renderer.py — ReportLab check face and reverse renderer.

Generates a compliant check PDF at exactly 1:1 scale with all driver
scaling disabled (buildspec.md §10.1):

  "Render deterministically to a fixed-geometry PDF at 1:1 with all scaling
   disabled in the driver. Embed the E-13B font as an outline or draw the
   characters as vector glyphs so the pitch cannot drift."

Layout implemented:
  Face (buildspec.md §6):
    - Drawer name and address (upper-left)
    - Check serial number (upper-right, large)
    - Date (upper-right, below serial)
    - Fractional routing number (upper-right block)
    - Payee line ("PAY TO THE ORDER OF ___")
    - Courtesy amount box (boxed, right-aligned, with $ and fill chars)
    - Legal (written) amount line with trailing asterisk fill
    - Bank name and city
    - Memo line (optional)
    - Signature line with microprinting border
    - MICR code line in the print band (E-13B font)
    - Clear band (empty, full width)
    - Padlock icon + security legend (§8, X9.100-170)
    - Void pantograph pattern (background, clear-band-safe)

  Reverse (buildspec.md §7):
    - "Endorse here" zone
    - BOFD (bank-of-first-deposit) clear zone (3.0 in from leading edge)
    - Security warning text

Units: all internal measurements are in points (1 pt = 1/72 in).
       Public API uses inches for human-readable geometry parameters.
"""

import datetime
import io
import os
import sys
from pathlib import Path

from reportlab.lib.units import inch
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Local modules
sys.path.insert(0, str(Path(__file__).parent))
from micr import build_code_line
from amounts import (
    cents_to_courtesy,
    cents_to_legal,
    cents_to_remittance_courtesy,
    cents_to_remittance_legal,
)


# ---------------------------------------------------------------------------
# E-13B font registration
# ---------------------------------------------------------------------------

_E13B_FONT_NAME  = "E13B"
_E13B_REGISTERED = False

# Fallback font if the E-13B OTF is not present.
_FALLBACK_FONT = "Courier"


def _register_e13b_font() -> str:
    """
    Register the E-13B MICR font with ReportLab.

    Returns the font name to use for MICR rendering.
    Searches for the font in fonts/ relative to the project root.
    If not found, falls back to Courier with a warning.
    """
    global _E13B_REGISTERED

    if _E13B_REGISTERED:
        return _E13B_FONT_NAME

    # Search for font file relative to this file's parent's parent (project root).
    project_root = Path(__file__).parent.parent
    candidates = [
        project_root / "fonts" / "e13b.ttf",
        project_root / "fonts" / "GnuMICR.ttf",
        project_root / "fonts" / "e13b.otf",
        project_root / "fonts" / "GnuMICR.otf",
    ]

    for font_path in candidates:
        if font_path.exists():
            try:
                pdfmetrics.registerFont(TTFont(_E13B_FONT_NAME, str(font_path)))
                _E13B_REGISTERED = True
                return _E13B_FONT_NAME
            except Exception as e:
                print(
                    f"WARNING: Could not register E-13B font {font_path}: {e}\n"
                    f"         Trying next candidate...",
                    file=sys.stderr,
                )
                continue

    print(
        f"WARNING: E-13B font not found (searched: {[str(c) for c in candidates]}).\n"
        f"         MICR characters will use {_FALLBACK_FONT}. "
        f"Download GnuMICR (https://sandeen.net/GnuMICR) and place in fonts/.\n"
        f"         Do NOT print live stock without the correct MICR font.",
        file=sys.stderr,
    )
    return _FALLBACK_FONT


# ---------------------------------------------------------------------------
# Geometry constants (in inches, converted to points below)
# ---------------------------------------------------------------------------

# Personal check dimensions: 6.0" wide by 2 3/4" (2.75") tall per Bank of America Spec Page 3
PERSONAL_WIDTH_IN  = 6.0
PERSONAL_HEIGHT_IN = 2.75  # Exactly 2 3/4 inch per BofA Engineering Spec

DEFAULT_WIDTH_IN  = 8.5
DEFAULT_HEIGHT_IN = 3.5

# Clear band: 0.625 in high, from the bottom edge.
CLEAR_BAND_HEIGHT_IN = 0.625
# Print band: 0.250 in high, centred in the clear band.
PRINT_BAND_HEIGHT_IN = 0.250
PRINT_BAND_BOTTOM_IN = (CLEAR_BAND_HEIGHT_IN - PRINT_BAND_HEIGHT_IN) / 2  # 0.1875 in

# MICR character width: 8 characters per inch (0.125 in/char)
MICR_CHAR_WIDTH_IN = 0.125
MICR_FONT_SIZE_PT  = 9.0  # 9 pt matches 0.117" character height per ANSI X9.100-20

# Margin
MARGIN_IN = 0.25

# Security legend height (approximate)
LEGEND_HEIGHT_IN = 0.15


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

# Pale blue-grey background (low saturation — images well under bitonal scan)
BACKGROUND_COLOR = colors.HexColor("#EDF2F7")

# Void pantograph pattern colour (very light — must clear the scan threshold)
PANTOGRAPH_COLOR = colors.HexColor("#D8E3EF")

# Standard ink colour for all text
TEXT_COLOR = colors.HexColor("#1A1A2E")

# Box / rule colour
RULE_COLOR = colors.HexColor("#4A5568")

# Security legend colour
LEGEND_COLOR = colors.HexColor("#718096")


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_check(
    check: dict,
    bank_config: dict,
    account_config: dict,
    output_path: str | Path,
    draw_signature: bool = False,
    signature_image_bytes: bytes | None = None,
    layout: str = "standard",
    remittance_data: dict | None = None,
    page_format: str = "check_only",
    include_background: bool = True,
) -> Path:
    """
    Render a complete check (face + reverse) to a PDF file.

    Parameters
    ----------
    check               : check record dict with keys:
                          serial_number, routing_number, account_number,
                          payee_name, amount_cents, issue_date, memo (optional)
    bank_config         : loaded bank_config.json
    account_config      : loaded account_config.json
    output_path         : where to write the PDF
    draw_signature      : if True, draw signature on the sig line
    signature_image_bytes : raw PNG/JPEG bytes (used if draw_signature=True)
    layout              : "standard" or "remittance" (USAA/BofA voucher check)
    remittance_data     : dict containing remittance fields (claim #, LOB, explanation, etc.)
    page_format         : "check_only" (8.5x3.5 in) or "voucher_sheet" (8.5x11 in)

    Returns the output_path as a Path.
    """
    if isinstance(output_path, (str, Path)):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target = str(output_path)
    else:
        target = output_path

    raw_layout = check.get("layout")
    if raw_layout:
        layout = str(raw_layout).lower()
        is_personal = layout in ("personal", "standard_personal", "standard") and not check.get("is_business", False)
    else:
        if layout in ("personal", "standard_personal"):
            is_personal = True
        elif layout in ("business", "remittance"):
            is_personal = False
        elif "check_dimensions" in account_config and account_config["check_dimensions"].get("width_in", 0) > 6.5:
            is_personal = False
        else:
            is_personal = not check.get("is_business", False)

    page_format = check.get("page_format", page_format)
    if remittance_data is None:
        remittance_data = check.get("remittance_data", {})

    micr_font = _register_e13b_font()

    if page_format == "voucher_sheet":
        w_in = 8.5
        h_in = 11.0
        check_h_in = PERSONAL_HEIGHT_IN if is_personal else account_config.get("check_dimensions", {}).get("height_in", DEFAULT_HEIGHT_IN)
    else:
        # check_only mode
        if "check_dimensions" in check:
            w_in = check["check_dimensions"].get("width_in", PERSONAL_WIDTH_IN if is_personal else DEFAULT_WIDTH_IN)
            h_in = check["check_dimensions"].get("height_in", PERSONAL_HEIGHT_IN if is_personal else DEFAULT_HEIGHT_IN)
            if w_in <= 6.5:
                is_personal = True
        elif "check_dimensions" in account_config:
            w_in = account_config["check_dimensions"].get("width_in", PERSONAL_WIDTH_IN if is_personal else DEFAULT_WIDTH_IN)
            h_in = account_config["check_dimensions"].get("height_in", PERSONAL_HEIGHT_IN if is_personal else DEFAULT_HEIGHT_IN)
            if w_in > 6.5:
                is_personal = False
            elif w_in <= 6.5:
                is_personal = True
        else:
            w_in = PERSONAL_WIDTH_IN if is_personal else DEFAULT_WIDTH_IN
            h_in = PERSONAL_HEIGHT_IN if is_personal else DEFAULT_HEIGHT_IN
        check_h_in = h_in

    w_pt = w_in * inch
    h_pt = h_in * inch

    c = rl_canvas.Canvas(target, pagesize=(w_pt, h_pt))
    c.setTitle(f"Check #{check['serial_number']}")
    c.setAuthor("chedck check printing system")

    # ------------------------------------------------------------------
    # FACE
    # ------------------------------------------------------------------
    if page_format == "voucher_sheet":
        if is_personal:
            if include_background:
                _draw_personal_voucher_stub(c, check, bank_config, account_config, w_in, h_in, check_h_in)
            _draw_personal_face(c, check, bank_config, account_config, micr_font, w_in=6.0, h_in=check_h_in,
                                draw_signature=draw_signature, signature_image_bytes=signature_image_bytes,
                                y_offset=0, x_offset=(w_in - 6.0)/2 * inch,
                                include_background=include_background)
        elif layout == "remittance":
            if include_background:
                _draw_voucher_stub(c, check, bank_config, account_config, remittance_data, w_in, h_in, check_h_in)
            _draw_remittance_face(c, check, bank_config, account_config, micr_font, w_in, check_h_in,
                                  draw_signature=draw_signature, signature_image_bytes=signature_image_bytes,
                                  remittance_data=remittance_data, y_offset=0,
                                  include_background=include_background)
        else:
            if include_background:
                _draw_voucher_stub(c, check, bank_config, account_config, remittance_data, w_in, h_in, check_h_in)
            _draw_face(c, check, bank_config, account_config, micr_font, w_in, check_h_in,
                       draw_signature=draw_signature, signature_image_bytes=signature_image_bytes, y_offset=0,
                       include_background=include_background)
    else:
        # check_only mode
        if is_personal:
            _draw_personal_face(c, check, bank_config, account_config, micr_font, w_in, h_in,
                                draw_signature=draw_signature, signature_image_bytes=signature_image_bytes,
                                y_offset=0, x_offset=0,
                                include_background=include_background)
        elif layout == "remittance":
            _draw_remittance_face(c, check, bank_config, account_config, micr_font, w_in, h_in,
                                  draw_signature=draw_signature, signature_image_bytes=signature_image_bytes,
                                  remittance_data=remittance_data, y_offset=0,
                                  include_background=include_background)
        else:
            _draw_face(c, check, bank_config, account_config, micr_font, w_in, h_in,
                       draw_signature=draw_signature, signature_image_bytes=signature_image_bytes, y_offset=0,
                       include_background=include_background)

    # ------------------------------------------------------------------
    # REVERSE (second page)
    # ------------------------------------------------------------------
    c.showPage()
    _draw_reverse(c, account_config, w_in, h_in)

    c.save()
    return output_path


# ---------------------------------------------------------------------------
# Face rendering
# ---------------------------------------------------------------------------

def resolve_drawer_address_lines(account_config: dict) -> tuple[str, str]:
    """
    Resolve drawer address lines with support for optional structured fields.

    Structured fields (preferred, optional):
      - drawer_address_line1, drawer_address_line2
      - drawer_city, drawer_state_province, drawer_postal_code, drawer_country

    Legacy fields (fallback):
      - drawer_address
      - drawer_city_state_zip
    """
    line1 = str(account_config.get("drawer_address_line1") or "").strip()
    line2_extra = str(account_config.get("drawer_address_line2") or "").strip()
    city = str(account_config.get("drawer_city") or "").strip()
    state = str(account_config.get("drawer_state_province") or "").strip()
    postal = str(account_config.get("drawer_postal_code") or "").strip()
    country = str(account_config.get("drawer_country") or "").strip()

    if line1 and line2_extra:
        line1 = f"{line1}, {line2_extra}"
    elif not line1 and line2_extra:
        line1 = line2_extra

    city_state = ", ".join(part for part in [city, state] if part)
    locality_parts = []
    if city_state and postal:
        locality_parts.append(f"{city_state} {postal}")
    elif city_state:
        locality_parts.append(city_state)
    elif postal:
        locality_parts.append(postal)
    if country:
        locality_parts.append(country)
    line2 = " · ".join(locality_parts)

    if not line1 or not line2:
        drawer_addr = account_config.get("drawer_address", "")
        if isinstance(drawer_addr, list):
            if not line1:
                line1 = str(drawer_addr[0]).strip() if len(drawer_addr) > 0 else ""
            if not line2:
                line2 = (
                    str(drawer_addr[1]).strip()
                    if len(drawer_addr) > 1
                    else str(account_config.get("drawer_city_state_zip", "")).strip()
                )
        else:
            if not line1:
                line1 = str(drawer_addr).strip()
            if not line2:
                line2 = str(account_config.get("drawer_city_state_zip", "")).strip()

    return line1, line2


def _draw_face(
    c, check, bank_config, account_config, micr_font, w_in, h_in,
    draw_signature: bool = False, signature_image_bytes: bytes | None = None, y_offset: float = 0.0,
    include_background: bool = True,
):
    """Draw the check face on the current ReportLab canvas page."""
    m = MARGIN_IN

    # -- Background (suppressed in outline-only / check-stock mode) -------
    if include_background:
        c.setFillColor(BACKGROUND_COLOR)
        c.rect(0, y_offset, w_in * inch, h_in * inch, fill=1, stroke=0)
        # -- Void pantograph pattern (background, clear-band-safe) ---------
        _draw_pantograph(c, w_in, h_in)
        # -- Security legend along the top edge ----------------------------
        _draw_security_legend(c, w_in, h_in)
    else:
        # Outline-only: draw a thin border so the check boundary is visible
        c.setStrokeColor(RULE_COLOR)
        c.setLineWidth(0.5)
        c.rect(0, y_offset, w_in * inch, h_in * inch, fill=0, stroke=1)

    # -- Drawer block (upper-left) -----------------------------------------
    c.setFillColor(TEXT_COLOR)
    drawer_x = m * inch
    drawer_y = (h_in - m - 0.15) * inch + y_offset

    c.setFont("Helvetica-Bold", 10)
    c.drawString(drawer_x, drawer_y, account_config.get("drawer_name", ""))

    drawer_addr_line, drawer_csz = resolve_drawer_address_lines(account_config)

    c.setFont("Helvetica", 9)
    c.drawString(drawer_x, drawer_y - 12, drawer_addr_line)
    c.drawString(drawer_x, drawer_y - 24, drawer_csz)

    # -- Upper-right block: serial, date, fractional routing ---------------
    block_right_x = (w_in - m) * inch
    block_top_y   = (h_in - m - 0.05) * inch + y_offset

    # Serial number (large)
    c.setFont("Helvetica-Bold", 14)
    serial_str = str(check["serial_number"])
    c.drawRightString(block_right_x, block_top_y, serial_str)

    # Date
    c.setFont("Helvetica", 9)
    issue_date = check.get("issue_date", "")
    if issue_date:
        try:
            dt = datetime.date.fromisoformat(issue_date)
            display_date = dt.strftime("%m/%d/%Y")
        except ValueError:
            display_date = issue_date
    else:
        display_date = datetime.date.today().strftime("%m/%d/%Y")

    c.drawRightString(block_right_x, block_top_y - 18, f"Date: {display_date}")

    # Fractional routing
    frac_rt = account_config.get("fractional_routing", "")
    c.setFont("Helvetica", 8)
    c.drawRightString(block_right_x, block_top_y - 32, frac_rt)

    # -- Date label (left of the date field) -------------------------------
    date_y = (h_in - m - 0.80) * inch + y_offset
    c.setFont("Helvetica", 9)
    c.setFillColor(RULE_COLOR)
    c.drawString(
        (w_in * 0.55) * inch,
        date_y + 4,
        "DATE",
    )
    _draw_rule(
        c,
        (w_in * 0.55 + 0.35) * inch,
        date_y,
        (w_in - m) * inch,
        date_y,
    )

    # -- Payee line --------------------------------------------------------
    payee_y = (h_in - m - 1.10) * inch + y_offset
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 9)
    c.drawString(drawer_x, payee_y + 4, "PAY TO THE ORDER OF")

    payee_label_w = c.stringWidth("PAY TO THE ORDER OF", "Helvetica", 9)
    payee_field_start = drawer_x + payee_label_w + 6

    # Print payee name
    c.setFont("Helvetica", 10)
    c.drawString(payee_field_start, payee_y + 4, check.get("payee_name", ""))

    # Payee underline
    _draw_rule(c, payee_field_start, payee_y, (w_in * 0.72) * inch, payee_y)

    # Optional Payee Address (lines 1 & 2)
    payee_addr_line1 = check.get("payee_address") or ""
    payee_addr_line2 = check.get("payee_city_state_zip") or ""
    if payee_addr_line1 or payee_addr_line2:
        c.saveState()
        c.setFont("Helvetica", 8)
        c.setFillColor(TEXT_COLOR)
        addr_y = payee_y - 9
        if payee_addr_line1:
            c.drawString(payee_field_start, addr_y, payee_addr_line1)
            addr_y -= 9
        if payee_addr_line2:
            c.drawString(payee_field_start, addr_y, payee_addr_line2)
        c.restoreState()

    # -- Courtesy amount box -----------------------------------------------
    box_x      = (w_in * 0.74) * inch
    box_y      = payee_y - 4
    box_width  = (w_in - m - w_in * 0.74) * inch
    box_height = 20

    c.setStrokeColor(RULE_COLOR)
    c.setFillColor(colors.white)
    c.rect(box_x, box_y, box_width, box_height, fill=1, stroke=1)

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 11)
    courtesy = cents_to_courtesy(check["amount_cents"])
    c.drawRightString(box_x + box_width - 4, box_y + 5, courtesy)

    # -- Legal amount line -------------------------------------------------
    legal_y = payee_y - 22
    c.setFont("Helvetica", 9)
    c.setFillColor(TEXT_COLOR)

    legal_text = cents_to_legal(check["amount_cents"], line_width=70)
    c.drawString(drawer_x, legal_y + 4, legal_text)
    _draw_rule(c, drawer_x, legal_y, (w_in - m) * inch, legal_y)

    # -- "DOLLARS" label at right of legal line ----------------------------
    c.setFont("Helvetica", 8)
    c.setFillColor(RULE_COLOR)
    c.drawRightString((w_in - m) * inch, legal_y + 4 + 10, "DOLLARS")

    # -- Bank name and city (Drawee Institution per BofA spec) ------------
    bank_y = legal_y - 22
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 8.5)
    bank_name = bank_config.get("bank_name", "Bank of America, N.A.")
    bank_city = bank_config.get("bank_city_state", "Dallas, TX")
    c.drawString(drawer_x, bank_y, f"{bank_name}  ·  {bank_city}")
    c.setFont("Helvetica", 7.0)
    c.setFillColor(RULE_COLOR)
    rt = check.get("routing_number") or account_config.get("routing_number", "111000012")
    c.drawString(drawer_x, bank_y - 9, f"ACH R/T {rt}")

    # -- Memo line ---------------------------------------------------------
    memo_y = CLEAR_BAND_HEIGHT_IN * inch + 0.32 * inch + y_offset
    c.setFont("Helvetica", 8)
    c.setFillColor(RULE_COLOR)
    c.drawString(drawer_x, memo_y + 8, "MEMO")
    memo_end_x = (w_in * 0.45) * inch
    _draw_rule(c, drawer_x + 0.36 * inch, memo_y, memo_end_x, memo_y)

    memo_text = check.get("memo", "")
    if memo_text:
        c.setFillColor(TEXT_COLOR)
        c.setFont("Helvetica", 9)
        c.drawString(drawer_x + 0.38 * inch, memo_y + 3, memo_text[:40])

    # -- Signature line with microprinting ---------------------------------
    sig_x_start = (w_in * 0.50) * inch
    sig_x_end   = (w_in - m) * inch
    sig_y       = CLEAR_BAND_HEIGHT_IN * inch + 0.28 * inch + y_offset

    _draw_microprint_line(c, sig_x_start, sig_y, sig_x_end, sig_y)
    c.setFillColor(RULE_COLOR)
    c.setFont("Helvetica", 7)
    c.drawString(sig_x_start, sig_y + 3, "AUTHORIZED SIGNATURE")

    if draw_signature:
        if signature_image_bytes:
            _draw_signature_image(c, signature_image_bytes, sig_x_start + 10, sig_y + 2,
                                  (sig_x_end - sig_x_start - 20), 28)
        else:
            _draw_script_signature(c, sig_x_start + 18, sig_y + 3)

    # -- Padlock icon (X9.100-170) -----------------------------------------
    _draw_padlock_icon(c, w_in, h_in)

    # -- Clear band (must be empty) ----------------------------------------
    c.setFillColor(colors.white)
    c.rect(0, y_offset, w_in * inch, CLEAR_BAND_HEIGHT_IN * inch, fill=1, stroke=0)

    # -- MICR code line in the print band ----------------------------------
    _draw_micr_line(c, check, bank_config, micr_font, w_in, y_offset=y_offset)


def _draw_personal_padlock_icon(c, icon_x: float, icon_y: float, with_text: bool = True):
    """Draw padlock security icon and 'Security Features Details on Back' per ANSI X9.100-170."""
    c.saveState()
    icon_w = 9.5
    icon_h = 8.5
    c.setStrokeColor(RULE_COLOR)
    c.setFillColor(colors.HexColor("#718096"))
    c.setLineWidth(0.7)
    # Shackle
    c.arc(icon_x + 1.6, icon_y + 4.8, icon_x + icon_w - 1.6, icon_y + 11.5, 0, 180)
    # Body
    c.rect(icon_x, icon_y, icon_w, icon_h, fill=1, stroke=1)
    # Keyhole
    c.setFillColor(colors.white)
    c.circle(icon_x + icon_w / 2, icon_y + icon_h / 2, 0.9, fill=1, stroke=0)
    if with_text:
        c.setFont("Helvetica", 3.8)
        c.setFillColor(RULE_COLOR)
        tx = icon_x + icon_w + 2.5
        c.drawString(tx, icon_y + 7.5, "Security")
        c.drawString(tx, icon_y + 3.5, "Features")
        c.drawString(tx, icon_y - 0.5, "Details on")
        c.drawString(tx, icon_y - 4.5, "Back")
    else:
        c.setFont("Helvetica-Bold", 4.5)
        c.setFillColor(RULE_COLOR)
        c.drawString(icon_x + icon_w + 2.5, icon_y + 3.0, "MP")
    c.restoreState()


def _draw_bofa_flag_logo(c, x: float, y: float, size: float = 12):
    """Draw Bank of America flagscape mark (red and blue striped bars)."""
    c.saveState()
    # Red bars (top and right)
    c.setFillColor(colors.HexColor("#E31837"))
    c.rect(x, y + size * 0.52, size * 0.42, size * 0.36, fill=1, stroke=0)
    c.rect(x + size * 0.50, y + size * 0.52, size * 0.50, size * 0.36, fill=1, stroke=0)
    # Blue bars (bottom)
    c.setFillColor(colors.HexColor("#002677"))
    c.rect(x + size * 0.12, y, size * 0.38, size * 0.40, fill=1, stroke=0)
    c.rect(x + size * 0.58, y, size * 0.42, size * 0.40, fill=1, stroke=0)
    c.restoreState()


def _draw_personal_face(
    c, check, bank_config, account_config, micr_font, w_in: float, h_in: float,
    draw_signature: bool = False, signature_image_bytes: bytes | None = None,
    y_offset: float = 0.0, x_offset: float = 0.0,
    include_background: bool = True,
):
    """
    Draw an authentic, legally compliant Bank of America Personal Check face
    strictly matching Bank of America Global Account Printing Specifications Page 3
    (6.0" wide × 2 3/4" high, 5/8" clear band, components 1 through 10).
    """
    m = 0.22 * inch

    # Background
    # Outer perimeter & background
    if include_background:
        c.setFillColor(colors.HexColor("#FAFBFD"))
        c.rect(x_offset, y_offset, w_in * inch, h_in * inch, fill=1, stroke=0)
        # Clear band (bottom 5/8 in = 0.625" high from bottom, pure white for MICR/MBR)
        c.setFillColor(colors.white)
        c.rect(x_offset + 1, y_offset + 1, w_in * inch - 2, CLEAR_BAND_HEIGHT_IN * inch - 1, fill=1, stroke=0)
        # Outer document border
        c.setStrokeColor(colors.HexColor("#000000"))
        c.setLineWidth(0.8)
        c.rect(x_offset, y_offset, w_in * inch, h_in * inch, fill=0, stroke=1)
        # Subtle perimeter security border
        c.setStrokeColor(colors.HexColor("#CBD5E1"))
        c.setLineWidth(0.5)
        c.rect(x_offset + 2.5, y_offset + 2.5, w_in * inch - 5.0, h_in * inch - 5.0, fill=0, stroke=1)
        # Faint security feature notice along top
        c.setFillColor(LEGEND_COLOR)
        c.setFont("Helvetica", 4.8)
        c.drawCentredString(
            x_offset + (w_in / 2) * inch,
            y_offset + (h_in - 0.10) * inch,
            "SECURITY FEATURES: Chemically reactive paper · Micro-printed border · Absence of features indicates copy",
        )
    else:
        c.setFillColor(colors.white)
        c.rect(x_offset + 1, y_offset + 1, w_in * inch - 2, CLEAR_BAND_HEIGHT_IN * inch - 1, fill=1, stroke=0)
        c.setStrokeColor(RULE_COLOR)
        c.setLineWidth(0.6)
        c.rect(x_offset, y_offset, w_in * inch, h_in * inch, fill=0, stroke=1)

    # Component 1 (Top-Left): Customer Name & Address (0.373 in = 26.9 pt from left)
    drawer_x = x_offset + 26.9
    drawer_y = y_offset + 175.0

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(drawer_x, drawer_y, account_config.get("drawer_name", "Minnie Hinds"))

    drawer_addr = account_config.get("drawer_address", "")
    if isinstance(drawer_addr, list):
        drawer_addr_line = drawer_addr[0] if len(drawer_addr) > 0 else ""
        drawer_csz = drawer_addr[1] if len(drawer_addr) > 1 else account_config.get("drawer_city_state_zip", "")
    else:
        drawer_addr_line = str(drawer_addr)
        drawer_csz = account_config.get("drawer_city_state_zip", "")

    c.setFont("Helvetica", 8.0)
    c.drawString(drawer_x, drawer_y - 11.0, drawer_addr_line)
    c.drawString(drawer_x, drawer_y - 22.0, drawer_csz)

    # Component 6 (Far Top-Right): Check Serial Number
    right_x = x_offset + 414.0  # 5.75 in from left
    c.setFont("Helvetica-Bold", 14.0)
    c.setFillColor(TEXT_COLOR)
    serial_str = str(check["serial_number"])
    c.drawRightString(right_x, drawer_y, serial_str)

    # Component 7 (To the left of Check No.): Fractional Routing
    frac_rt = account_config.get("fractional_routing", "32-1 / 1110 GL")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawRightString(x_offset + 355.0, drawer_y, frac_rt)

    # Component 8: Date Line (y = 152.7 pt)
    date_y = y_offset + 152.7
    c.setFont("Helvetica-Bold", 8.0)
    c.setFillColor(RULE_COLOR)
    c.drawString(x_offset + 272.0, date_y + 3, "Date")
    _draw_rule(c, x_offset + 290.7, date_y, x_offset + 370.7, date_y)

    issue_date = check.get("issue_date", "")
    if issue_date:
        try:
            dt = datetime.date.fromisoformat(issue_date)
            display_date = dt.strftime("%m/%d/%Y")
        except ValueError:
            display_date = issue_date
    else:
        display_date = datetime.date.today().strftime("%m/%d/%Y")

    c.setFont("Helvetica", 8.5)
    c.setFillColor(TEXT_COLOR)
    c.drawRightString(x_offset + 368.0, date_y + 3, display_date)

    # Component 2: Pay to the order of (Stacked per BofA spec)
    payee_y = y_offset + 117.9
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(drawer_x, payee_y + 9.0, "Pay to the")
    c.drawString(drawer_x, payee_y - 1.0, "order of")

    payee_start_x = drawer_x + 51.1  # 78.0 pt

    # Component 9: Courtesy Amount Box
    box_w = 67.1   # 0.932 in
    box_h = 23.4   # 0.324 in
    box_x = x_offset + 317.6
    box_y = payee_y + 0.6

    # Dollar sign preceding the box
    c.setFont("Helvetica-Bold", 11.0)
    c.setFillColor(TEXT_COLOR)
    c.drawString(box_x - 11.6, box_y + 3.5, "$")

    # Payee underline
    _draw_rule(c, payee_start_x, payee_y, box_x - 16, payee_y)

    # Print payee name
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(payee_start_x + 4, payee_y + 2.5, check.get("payee_name", ""))

    # Box 9
    c.setStrokeColor(RULE_COLOR)
    c.setFillColor(colors.white)
    c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=1)

    # Inside box amount
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 10.5)
    courtesy = cents_to_courtesy(check["amount_cents"])
    box_courtesy = courtesy.lstrip("$*")
    if not box_courtesy:
        box_courtesy = courtesy
    c.drawRightString(box_x + box_w - 4, box_y + 4.5, box_courtesy)

    # Optional Payee Address
    payee_addr_line1 = check.get("payee_address") or ""
    payee_addr_line2 = check.get("payee_city_state_zip") or ""
    if payee_addr_line1 or payee_addr_line2:
        c.saveState()
        c.setFont("Helvetica", 7.0)
        c.setFillColor(TEXT_COLOR)
        if payee_addr_line1:
            c.drawString(payee_start_x + 4, payee_y - 9, payee_addr_line1)
        if payee_addr_line2:
            c.drawString(payee_start_x + 4, payee_y - 17, payee_addr_line2)
        c.restoreState()

    # Component 3: Legal Amount Line ending in "Dollars"
    legal_y = y_offset + 95.2
    c.setFont("Helvetica", 8.5)
    c.setFillColor(TEXT_COLOR)
    legal_text = cents_to_legal(check["amount_cents"], line_width=52)
    c.drawString(drawer_x, legal_y + 3, legal_text)

    _draw_rule(c, drawer_x, legal_y, x_offset + 371.3, legal_y)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(RULE_COLOR)
    c.drawRightString(right_x, legal_y + 3, "Dollars")

    # Component 4: Bank of America Flag Logo, Bank Name, and ACH R/T
    bank_y = y_offset + 74.0
    _draw_bofa_flag_logo(c, drawer_x, bank_y - 2, size=11)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(TEXT_COLOR)
    bank_name = bank_config.get("bank_name", "Bank of America")
    c.drawString(drawer_x + 15, bank_y, bank_name)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#475569"))
    rt = check.get("routing_number") or account_config.get("routing_number", "111000012")
    c.drawString(drawer_x, bank_y - 8.5, f"ACH R/T {rt}")

    # Memo Line and Signature Line:
    # Positioned at y = 59.2 pt (0.82 in) from the bottom edge per BofA spec
    bottom_ctrl_y = y_offset + 59.2

    # Memo: 'Memo ________________________'
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(RULE_COLOR)
    c.drawString(drawer_x, bottom_ctrl_y + 3, "Memo")
    memo_rule_end = x_offset + 138.9
    _draw_rule(c, drawer_x + 30.9, bottom_ctrl_y, memo_rule_end, bottom_ctrl_y)

    memo_text = check.get("memo", "")
    if memo_text:
        c.setFont("Helvetica", 8.0)
        c.setFillColor(TEXT_COLOR)
        c.drawString(drawer_x + 33, bottom_ctrl_y + 3, memo_text[:30])

    # Component 10: Signature Line
    sig_x_start = x_offset + 310.0
    sig_x_end = x_offset + 420.9
    _draw_microprint_line(c, sig_x_start, bottom_ctrl_y, sig_x_end, bottom_ctrl_y)

    if draw_signature:
        if signature_image_bytes:
            _draw_signature_image(c, signature_image_bytes, sig_x_start + 4, bottom_ctrl_y + 1,
                                  (sig_x_end - sig_x_start - 8), 22)
        else:
            _draw_script_signature(c, sig_x_start + 8, bottom_ctrl_y + 2)

    # Personal MICR line
    _draw_micr_line(c, check, bank_config, micr_font, w_in, y_offset=y_offset, x_offset=x_offset)


def _draw_personal_voucher_stub(c, check, bank_config, account_config, w_in: float, h_in: float, check_h_in: float):
    """
    Draw personal check transaction record and register on an 8.5" x 11" voucher sheet.
    Personal check face sits at the bottom (y = 0 to check_h_in).
    """
    c.saveState()
    # Perforation guide line above check
    perf_y = (check_h_in + 0.15) * inch
    c.setStrokeColor(colors.HexColor("#94A3B8"))
    c.setDash(4, 4)
    c.line(0.5 * inch, perf_y, (w_in - 0.5) * inch, perf_y)
    c.setDash()

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawCentredString((w_in / 2) * inch, perf_y + 4, "✂   DETACH BEFORE CASHING   ·   PERSONAL RECORD BELOW   ✂")

    # Header for personal transaction record
    stub_bottom = perf_y + 12
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0.5 * inch, stub_bottom, (w_in - 1.0) * inch, (h_in * inch - stub_bottom - 0.3 * inch), fill=1, stroke=0)

    stub_top_y = (h_in - 0.5) * inch
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor("#1E293B"))
    c.drawString(0.8 * inch, stub_top_y, "PERSONAL CHECK TRANSACTION RECORD & REGISTER")

    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(0.8 * inch, stub_top_y - 12, "Retain this portion for your personal records, budget tracking, and tax accounting.")

    # Record summary card
    card_y = stub_top_y - 82
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.rect(0.8 * inch, card_y, (w_in - 1.6) * inch, 60, fill=1, stroke=1)

    courtesy = cents_to_courtesy(check['amount_cents'])
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(1.0 * inch, card_y + 44, f"CHECK #{check['serial_number']}")
    c.drawString(2.8 * inch, card_y + 44, f"DATE: {check.get('issue_date', '')}")
    c.drawRightString((w_in - 1.0) * inch, card_y + 44, f"AMOUNT: {courtesy}")

    c.setFont("Helvetica", 8.0)
    c.drawString(1.0 * inch, card_y + 26, f"PAYEE: {check.get('payee_name', '')}")
    memo = check.get('memo', '')
    if memo:
        c.drawString(1.0 * inch, card_y + 10, f"MEMO: {memo}")

    # Check Register Table
    reg_y = card_y - 28
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(0.8 * inch, reg_y, "CHECK REGISTER ENTRIES")

    # Table header
    th_y = reg_y - 18
    c.setFillColor(colors.HexColor("#EEF2F6"))
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.rect(0.8 * inch, th_y, (w_in - 1.6) * inch, 16, fill=1, stroke=1)

    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(0.9 * inch, th_y + 5, "CHECK #")
    c.drawString(1.6 * inch, th_y + 5, "DATE")
    c.drawString(2.4 * inch, th_y + 5, "DESCRIPTION / PAYEE")
    c.drawString(5.0 * inch, th_y + 5, "PAYMENT (-)")
    c.drawString(5.9 * inch, th_y + 5, "FEE")
    c.drawString(6.6 * inch, th_y + 5, "DEPOSIT (+)")
    c.drawString(7.3 * inch, th_y + 5, "BALANCE")

    # 6 blank register rows
    row_h = 24.0
    for r in range(6):
        ry = th_y - (r + 1) * row_h
        c.setFillColor(colors.white if r % 2 == 0 else colors.HexColor("#FAFAFA"))
        c.rect(0.8 * inch, ry, (w_in - 1.6) * inch, row_h, fill=1, stroke=1)
        if r == 0:
            c.setFont("Helvetica", 7.0)
            c.setFillColor(colors.HexColor("#1E293B"))
            c.drawString(0.9 * inch, ry + 8, str(check['serial_number']))
            c.drawString(1.6 * inch, ry + 8, check.get('issue_date', ''))
            c.drawString(2.4 * inch, ry + 8, check.get('payee_name', '')[:30])
            c.drawString(5.0 * inch, ry + 8, courtesy)

    c.restoreState()


def _draw_micr_line(c, check, bank_config, micr_font, w_in, y_offset: float = 0.0, x_offset: float = 0.0):
    """
    Draw the ANSI X9.100-160-1 / ANSI X9.27 E-13B MICR code line.
    Position 1 is anchored 0.3125 in (5/16 in) from the right (leading) edge.
    Pitch is standard ANSI 8 CPI (0.125 in = 9.0 pt) with character baseline
    centered in the 0.625 in clear band.
    """
    code_line = build_code_line(check, bank_config)

    char_w  = MICR_CHAR_WIDTH_IN * inch  # 0.125 in = 9.0 pt (8 CPI per ANSI X9.27 / X9.100-20)
    font_sz = MICR_FONT_SIZE_PT         # 9.0 pt
    micr_y  = y_offset + PRINT_BAND_BOTTOM_IN * inch + 3.0

    c.setFillColor(colors.black)

    for i, ch in enumerate(code_line):
        if ch != " ":
            pos = 65 - i
            x = x_offset + w_in * inch - (0.3125 * inch + (pos - 1) * char_w)
            _draw_micr_glyph(c, ch, x, micr_y, char_w, micr_font, font_sz)


# ---------------------------------------------------------------------------
# Remittance (USAA / Voucher) face rendering
# ---------------------------------------------------------------------------

def _draw_signature_image(c, image_bytes: bytes, x: float, y: float, max_w: float, max_h: float):
    """Draw a raster signature image from raw bytes with aspect ratio preserved."""
    try:
        img = ImageReader(io.BytesIO(image_bytes))
        iw, ih = img.getSize()
        scale = min(max_w / iw, max_h / ih)
        w = iw * scale
        h = ih * scale
        c.drawImage(img, x, y, width=w, height=h, mask='auto')
    except Exception as e:
        print(f"Warning: could not draw signature image: {e}", file=sys.stderr)


def _draw_script_signature(c, x: float, y: float, name: str = "Minnie Hinds"):
    """Draw an authentic cursive script signature using Bezier curve paths."""
    c.saveState()
    c.setStrokeColor(colors.HexColor("#0D1B2A"))
    c.setLineWidth(1.1)

    p = c.beginPath()
    # Initial capital letter flourish (M)
    p.moveTo(x, y + 2)
    p.curveTo(x + 2, y + 16, x + 5, y + 19, x + 8, y + 4)
    p.curveTo(x + 11, y + 15, x + 13, y + 16, x + 16, y + 2)
    # Cursive middle letters
    p.curveTo(x + 19, y + 8, x + 21, y + 7, x + 24, y + 3)
    p.curveTo(x + 26, y + 8, x + 28, y + 7, x + 31, y + 3)
    p.curveTo(x + 33, y + 8, x + 36, y + 7, x + 39, y + 3)
    p.curveTo(x + 42, y + 8, x + 44, y + 6, x + 47, y + 2)
    # Second capital letter (H)
    p.moveTo(x + 54, y + 22)
    p.curveTo(x + 53, y + 12, x + 54, y + 2, x + 55, y + 3)
    p.moveTo(x + 63, y + 18)
    p.curveTo(x + 62, y + 10, x + 63, y + 2, x + 64, y + 3)
    p.moveTo(x + 52, y + 10)
    p.curveTo(x + 58, y + 11, x + 65, y + 10, x + 69, y + 7)
    # Ending letters and terminal flourish
    p.curveTo(x + 72, y + 10, x + 75, y + 7, x + 79, y + 4)
    p.curveTo(x + 82, y + 18, x + 83, y + 16, x + 85, y + 3)
    p.curveTo(x + 88, y + 8, x + 91, y + 11, x + 96, y + 8)
    # Underline flourish
    p.curveTo(x + 88, y - 2, x + 65, y - 3, x + 42, y - 2)
    c.drawPath(p, stroke=1, fill=0)

    # Dots on 'i's
    c.setFillColor(colors.HexColor("#0D1B2A"))
    c.circle(x + 22, y + 11, 0.75, fill=1, stroke=0)
    c.circle(x + 74, y + 12, 0.75, fill=1, stroke=0)

    c.restoreState()


def _draw_usaa_logo(c, x: float, y: float, w: float = 34.0, h: float = 35.6):
    """
    Draw the authentic official USAA eagle emblem and USAA logotype.
    Uses high-resolution transparent vector-derived raster assets/usaa_logo_navy.png.
    """
    project_root = Path(__file__).parent.parent
    logo_file = project_root / "assets" / "usaa_logo_navy.png"
    if logo_file.exists():
        try:
            img = ImageReader(str(logo_file))
            c.drawImage(img, x, y, width=w, height=h, mask='auto')
            return
        except Exception as e:
            print(f"Warning: could not load USAA logo image {logo_file}: {e}", file=sys.stderr)

    c.saveState()
    c.setFillColor(colors.HexColor("#122443"))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x, y + 5, "USAA")
    c.setFont("Helvetica", 4.5)
    c.drawString(x + 24, y + 8, "®")
    c.restoreState()


def _draw_micr_glyph(c, ch: str, x: float, y: float, char_w: float, font_name: str, font_sz: float):
    """
    Draw an E-13B character.
    If true E-13B font is registered:
      Maps special symbols to the font's ASCII glyph mappings:
        Transit (⑆, \u2446) -> 'T'
        On-Us (⑈, \u2448 / \u2447) -> 'O'
        Amount (⑇, \u2447)  -> 'A'
        Dash (⑉, \u2449)    -> 'D'
        Digits '0'-'9'       -> '0'-'9'
    If fallback font (Courier):
      Renders vector glyphs for the special delimiter symbols.
    """
    is_fallback = (font_name == _FALLBACK_FONT)
    c.saveState()
    c.setFillColor(colors.black)
    if is_fallback and ch in ("\u2447", "\u2448", "C", "c", "O", "o"):
        # On-Us symbol (⑈): two vertical bars with two horizontal tick marks
        bar_w = 1.05
        bar_h = 7.8
        by = y + 0.8
        # Left and right bars
        c.rect(x + 1.2, by, bar_w, bar_h, fill=1, stroke=0)
        c.rect(x + char_w - 2.2, by, bar_w, bar_h, fill=1, stroke=0)
        # Center tick marks (top and bottom)
        c.rect(x + 2.2, by + bar_h - 1.8, char_w - 4.4, 1.1, fill=1, stroke=0)
        c.rect(x + 2.2, by + 0.7, char_w - 4.4, 1.1, fill=1, stroke=0)
    elif is_fallback and ch in ("\u2446", "T", "t"):
        # Transit symbol (⑆): vertical bars connected top and bottom
        bar_w = 1.05
        bar_h = 7.8
        by = y + 0.8
        c.rect(x + 1.5, by, bar_w, bar_h, fill=1, stroke=0)
        c.rect(x + char_w - 2.5, by, bar_w, bar_h, fill=1, stroke=0)
        c.rect(x + 1.5, by + bar_h - 1.2, char_w - 3.0, 1.2, fill=1, stroke=0)
        c.rect(x + 1.5, by, char_w - 3.0, 1.2, fill=1, stroke=0)
    elif is_fallback and ch in ("A", "a", "B", "b"):
        # Amount symbol (⑇)
        c.rect(x + 2.0, y + 1.5, char_w - 4.0, 6.5, fill=1, stroke=0)
    elif is_fallback and ch in ("\u2449", "D", "d"):
        # Dash symbol (⑉)
        c.rect(x + 1.5, y + 3.8, char_w - 3.0, 1.4, fill=1, stroke=0)
    elif is_fallback:
        c.setFont("Helvetica-Bold", font_sz)
        c.drawString(x, y, ch)
    else:
        # Authentic ANSI X9.100-20 E-13B font
        # Map Unicode or alternate characters to E-13B font ASCII mappings:
        mapping = {
            "\u2446": "T",
            "\u2448": "O",
            "\u2447": "O",
            "\u2449": "D",
            "C": "O",
            "c": "O",
            "t": "T",
            "o": "O",
            "a": "A",
            "d": "D",
            "T": "T",
            "O": "O",
            "A": "A",
            "D": "D",
        }
        glyph_char = mapping.get(ch, ch)
        c.setFont(font_name, font_sz)
        c.drawString(x, y, glyph_char)
    c.restoreState()


def _draw_remittance_micr_line(c, check, bank_config, account_config, remittance_data, micr_font, w_in, y_offset: float = 0.0):
    """
    Draw ANSI X9.100 E-13B code line specifically matching the USAA Remittance voucher check format:
      ⑈[10-digit serial]⑈   ⑆[9-digit transit]⑆   [12-digit account]⑈
    Characters are placed left-to-right at the standard 8 CPI pitch (0.125 in / 9 pt).
    """
    # 1. Prepare fields
    raw_serial = check["serial_number"]
    pad = remittance_data.get("serial_padding", 10)
    serial_str = str(raw_serial).zfill(pad) if pad else str(raw_serial)

    routing_str = remittance_data.get("routing_number", account_config.get("routing_number", "011900445"))
    account_str = remittance_data.get("account_number", account_config.get("account_number", "007740015665"))

    line_chars = [" "] * 65

    def set_char(pos: int, ch: str):
        if 1 <= pos <= 65:
            line_chars[65 - pos] = ch

    # Aux On-Us: positions 58 down to 47 -> ⑈ + 10 digits + ⑈
    set_char(58, "\u2447")
    for i, digit in enumerate(serial_str):
        set_char(57 - i, digit)
    set_char(57 - len(serial_str), "\u2447")

    # Transit: positions 43 down to 33 -> ⑆ + 9 digits + ⑆
    set_char(43, "\u2446")
    for i, digit in enumerate(routing_str):
        set_char(42 - i, digit)
    set_char(42 - len(routing_str), "\u2446")

    # On-Us (Account): positions 31 down to 19 -> 12 digits + ⑈
    for i, digit in enumerate(account_str):
        set_char(31 - i, digit)
    set_char(31 - len(account_str), "\u2447")

    # Render characters
    micr_y = y_offset + PRINT_BAND_BOTTOM_IN * inch + 3
    char_w = MICR_CHAR_WIDTH_IN * inch
    font_sz = MICR_FONT_SIZE_PT

    x = 0.0
    for ch in line_chars:
        if ch != " ":
            _draw_micr_glyph(c, ch, x, micr_y, char_w, micr_font, font_sz)
        x += char_w


def _draw_remittance_face(
    c, check, bank_config, account_config, micr_font, w_in, h_in,
    draw_signature: bool = False, signature_image_bytes: bytes | None = None,
    remittance_data: dict | None = None, y_offset: float = 0.0,
    include_background: bool = True,
):
    """
    Draw the corporate/insurance remittance check face (USAA / Bank of America style).
    Accurately proportioned to match official corporate remittance check stock.
    """
    if remittance_data is None:
        remittance_data = {}

    m = 0.40 * inch
    c.saveState()

    # 0. Background tint (suppressed in outline-only / check-stock mode)
    if include_background:
        c.setFillColor(colors.HexColor("#F8FAFD"))
        c.rect(0, y_offset, w_in * inch, h_in * inch, fill=1, stroke=0)

        # Soft lavender watercolor cloud wash under the purple bar
        c.saveState()
        wash_y = y_offset + (h_in - 1.10) * inch
        c.setFillColor(colors.HexColor("#EDEAF6"))
        p_wash = c.beginPath()
        p_wash.moveTo(m, y_offset + (h_in - 0.44) * inch)
        p_wash.lineTo(m + 3.2 * inch, y_offset + (h_in - 0.44) * inch)
        p_wash.curveTo(m + 2.8 * inch, wash_y + 0.3 * inch, m + 1.8 * inch, wash_y + 0.1 * inch, m + 1.2 * inch, wash_y + 0.2 * inch)
        p_wash.curveTo(m + 0.6 * inch, wash_y + 0.3 * inch, m + 0.2 * inch, wash_y + 0.1 * inch, m, wash_y + 0.2 * inch)
        p_wash.close()
        c.drawPath(p_wash, fill=1, stroke=0)
        c.restoreState()
    else:
        # Outline-only: thin border only
        c.setStrokeColor(colors.HexColor("#4A5568"))
        c.setLineWidth(0.5)
        c.rect(0, y_offset, w_in * inch, h_in * inch, fill=0, stroke=1)

    # 1. Top Control Header (above purple bar)
    stub_y = y_offset + (h_in - 0.22) * inch

    # Left control number with subtle border
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#4A5568"))
    ctl_l = remittance_data.get("control_number_left", "500489-1221")
    ctl_lw = 0.68 * inch
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.4)
    c.rect(m, stub_y - 2, ctl_lw, 10.5, fill=0, stroke=1)
    c.drawCentredString(m + ctl_lw / 2, stub_y + 1, ctl_l)

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawCentredString((w_in / 2) * inch, stub_y,
                        remittance_data.get("voucher_header_text", "RETAIN THE TOP PORTION FOR YOUR RECORDS"))

    # Right control number with subtle border
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#4A5568"))
    ctl_r = remittance_data.get("control_number_right", "136366-0520")
    ctl_w = 0.70 * inch
    ctl_x = (w_in * inch) - m - ctl_w
    c.rect(ctl_x, stub_y - 2, ctl_w, 10.5, fill=0, stroke=1)
    c.drawCentredString(ctl_x + ctl_w / 2, stub_y + 1, ctl_r)

    # 2. Purple Security Warning Bar (background only)
    bar_y = y_offset + (h_in - 0.44) * inch
    bar_h = 10.5
    bar_w = (w_in * inch) - (2 * m)
    if include_background:
        c.setFillColor(colors.HexColor("#342268"))
        c.rect(m, bar_y, bar_w, bar_h, fill=1, stroke=0)
        security_bar_text = remittance_data.get(
            "security_bar_text",
            "FACE OF DOCUMENT HAS A COLORED BACKGROUND. THE BACK CONTAINS AN ARTIFICIAL WATERMARK. HOLD AT ANGLE TO VIEW."
        )
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 4.6)
        c.drawCentredString((w_in / 2) * inch, bar_y + 3.2, security_bar_text)
    else:
        # Outline-only: draw a thin rule where the bar would be
        c.setStrokeColor(colors.HexColor("#4A5568"))
        c.setLineWidth(0.5)
        c.rect(m, bar_y, bar_w, bar_h, fill=0, stroke=1)

    # 3. USAA Logo (Header Left)
    # 4. Date and Serial Box (Header Right)
    box_w = 2.18 * inch
    box_h = 0.38 * inch
    box_x = (w_in * inch) - m - box_w
    box_y = y_offset + (h_in - 0.94) * inch
    box_center_y = box_y + (box_h / 2.0)

    box_top_y = box_y + box_h
    logo_w = 34.0
    logo_h = 35.6
    logo_x = m + 0.05 * inch
    logo_y = box_top_y - 1.5 - logo_h

    custom_logo = remittance_data.get("logo_image")
    if custom_logo and os.path.exists(custom_logo):
        try:
            img = ImageReader(custom_logo)
            c.drawImage(img, logo_x, logo_y, width=logo_w, height=logo_h, mask='auto')
        except Exception:
            _draw_usaa_logo(c, logo_x, logo_y, w=logo_w, h=logo_h)
    else:
        _draw_usaa_logo(c, logo_x, logo_y, w=logo_w, h=logo_h)

    # Drawer Address (indented next to logo - vertically centered with Date Box)
    drawer_x = m + 0.75 * inch
    c.setFillColor(colors.HexColor("#1A202C"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(drawer_x, box_center_y + 6.8, account_config.get("drawer_name", "USAA"))
    c.setFont("Helvetica", 6.8)
    drawer_addr_line, drawer_csz = resolve_drawer_address_lines(account_config)

    c.drawString(drawer_x, box_center_y - 2.7, drawer_addr_line)
    c.drawString(drawer_x, box_center_y - 12.2, drawer_csz)

    # 4. Drawee Bank & Fractional Routing (Header Middle - vertically centered with Date Box)
    bank_x = (w_in * 0.43) * inch
    c.setFont("Helvetica-Bold", 8.0)
    c.drawString(bank_x, box_center_y + 1.2, bank_config.get("bank_name", "Bank of America"))
    c.setFont("Helvetica", 7.2)
    c.drawString(bank_x, box_center_y - 8.3, bank_config.get("bank_city_state", "Hartford,CT"))

    frac_x = (w_in * 0.59) * inch
    c.drawString(frac_x, box_center_y - 2.6, account_config.get("fractional_routing", "51-44/119 CT"))

    # Date and Serial Box Border & Fill
    c.setStrokeColor(colors.HexColor("#2D3748"))
    c.setLineWidth(0.75)
    c.setFillColor(colors.white)
    c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=1)

    # Divider
    div_w = 0.90 * inch
    c.line(box_x + div_w, box_y, box_x + div_w, box_y + box_h)

    # Date cell (left - vertically centered)
    c.setFillColor(colors.HexColor("#1A202C"))
    c.setFont("Helvetica-Bold", 7.0)
    c.drawCentredString(box_x + div_w / 2, box_center_y + 3.0, "DATE")

    issue_date = check.get("issue_date", "")
    if issue_date:
        try:
            dt = datetime.date.fromisoformat(issue_date)
            display_date = dt.strftime("%m/%d/%Y")
        except ValueError:
            display_date = issue_date
    else:
        display_date = datetime.date.today().strftime("%m/%d/%Y")

    c.setFont("Helvetica", 8.2)
    c.drawCentredString(box_x + div_w / 2, box_center_y - 7.5, display_date)

    # Serial cell (right - vertically centered)
    raw_serial = check["serial_number"]
    pad = remittance_data.get("serial_padding", 10)
    serial_str = str(raw_serial).zfill(pad) if pad else str(raw_serial)
    c.setFont("Helvetica-Bold", 11.0)
    c.drawCentredString(box_x + div_w + (box_w - div_w) / 2, box_center_y - 3.8, serial_str)

    # 6. Legal Amount Line (Above Payee!)
    legal_x = drawer_x
    legal_y = y_offset + (h_in - 1.22) * inch
    legal_text = cents_to_remittance_legal(check["amount_cents"])
    c.setFont("Helvetica-Bold", 8.0)
    c.setFillColor(colors.HexColor("#1A202C"))
    c.drawString(legal_x, legal_y + 3, legal_text)

    # Underline beneath the legal amount text extending across to the Date/Serial box
    c.setStrokeColor(colors.HexColor("#4A5568"))
    c.setLineWidth(0.55)
    line_end_x = box_x + div_w
    c.line(legal_x, legal_y + 0.2, line_end_x, legal_y + 0.2)

    # 7. Payee Line & Stacked Label
    payee_label_x = m + 0.22 * inch
    payee_y = y_offset + (h_in - 1.62) * inch
    c.setFont("Helvetica-Bold", 5.8)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawString(payee_label_x, payee_y + 13, "Pay To")
    c.drawString(payee_label_x, payee_y + 6.5, "The")
    c.drawString(payee_label_x, payee_y, "Order")
    c.drawString(payee_label_x, payee_y - 6.5, "Of:")

    payee_x = legal_x
    c.setFont("Helvetica", 8.8)
    c.setFillColor(colors.HexColor("#1A202C"))
    c.drawString(payee_x, payee_y + 11, check.get("payee_name", ""))

    # 8. Courtesy Amount Box & LOB Classification (positioned below Date Box, around y ~ 1.55 in)
    courtesy_str = cents_to_remittance_courtesy(check["amount_cents"])
    amt_y = y_offset + (h_in - 1.95) * inch
    c.setFont("Helvetica-Bold", 11.5)
    c.drawRightString((w_in * inch) - m, amt_y, courtesy_str)

    lob_text = remittance_data.get("line_of_business", "LOB: P&C")
    c.setFont("Helvetica", 7.0)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawRightString((w_in * inch) - m, amt_y - 13, lob_text)

    # 9. Remittance Metadata Table (stops cleanly before signature block)
    tbl_x = payee_label_x
    tbl_y = y_offset + (h_in - 2.22) * inch
    tbl_w = 4.55 * inch
    tbl_h = 0.28 * inch

    c.setStrokeColor(colors.HexColor("#2D3748"))
    c.setLineWidth(0.65)
    c.setFillColor(colors.white)
    c.rect(tbl_x, tbl_y, tbl_w, tbl_h, fill=1, stroke=1)

    # Header / data divider line
    c.line(tbl_x, tbl_y + 9.5, tbl_x + tbl_w, tbl_y + 9.5)

    # 4 columns: USAA #, LOSS RPT #, LOSS DATE, POLICYHOLDER
    cols = [
        (remittance_data.get("col1_header", "USAA #"),
         remittance_data.get("col1_value", "005361319"), 0.90 * inch),
        (remittance_data.get("col2_header", "LOSS RPT #"),
         remittance_data.get("col2_value", "12"), 0.95 * inch),
        (remittance_data.get("col3_header", "LOSS DATE"),
         remittance_data.get("col3_value", "2023-07-22"), 1.10 * inch),
        (remittance_data.get("col4_header", "POLICYHOLDER"),
         remittance_data.get("col4_value", "JAMES L GRASS"), 1.60 * inch),
    ]

    curr_x = tbl_x
    for i, (hdr, val, cw) in enumerate(cols):
        if i > 0:
            c.line(curr_x, tbl_y, curr_x, tbl_y + tbl_h)
        c.setFont("Helvetica-Bold", 5.8)
        c.setFillColor(colors.HexColor("#2D3748"))
        c.drawCentredString(curr_x + cw / 2, tbl_y + tbl_h - 7.5, hdr)
        c.setFont("Helvetica", 6.8)
        c.setFillColor(colors.HexColor("#1A202C"))
        c.drawCentredString(curr_x + cw / 2, tbl_y + 2.5, val)
        curr_x += cw

    # 10. Payment Explanation
    exp_y = tbl_y - 12
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(tbl_x, exp_y, remittance_data.get("explanation_title", "PAYMENT EXPLANATION:"))
    exp_text = remittance_data.get("explanation_text", "Payment under Medical Payments to Others coverage")
    c.setFont("Helvetica", 6.5)
    c.drawString(tbl_x, exp_y - 8.5, exp_text)

    # 11. Stale Date Notice (safely above clear band)
    stale_text = remittance_data.get("stale_date_text", "VOID 180 DAYS FROM ISSUE DATE")
    c.setFont("Helvetica", 6.8)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawCentredString((w_in / 2) * inch, y_offset + 0.85 * inch, stale_text)

    # 12. Signature Block (Lower Right)
    sig_x_start = 5.50 * inch
    sig_x_end   = (w_in * inch) - m
    sig_y       = y_offset + 0.85 * inch

    c.setStrokeColor(colors.HexColor("#2D3748"))
    c.setLineWidth(0.65)
    c.line(sig_x_start, sig_y, sig_x_end, sig_y)

    c.setFont("Helvetica", 6.5)
    c.drawCentredString(sig_x_start + (sig_x_end - sig_x_start) / 2, sig_y - 8.5, "Authorized Signature")

    if draw_signature:
        if signature_image_bytes:
            _draw_signature_image(c, signature_image_bytes, sig_x_start + 10, sig_y + 2,
                                  (sig_x_end - sig_x_start - 20), 28)
        else:
            sig_name = remittance_data.get("signature_name", "Minnie Hinds")
            _draw_script_signature(c, sig_x_start + 18, sig_y + 3, name=sig_name)

    # 13. Clear band (0.625" pure white at bottom)
    c.setFillColor(colors.white)
    c.rect(0, y_offset, w_in * inch, CLEAR_BAND_HEIGHT_IN * inch, fill=1, stroke=0)

    # 14. MICR code line
    _draw_remittance_micr_line(c, check, bank_config, account_config, remittance_data, micr_font, w_in, y_offset=y_offset)

    c.restoreState()


def _draw_voucher_stub(c, check, bank_config, account_config, remittance_data, w_in, h_in, check_h_in):
    """
    Draw top voucher / remittance statement on letter-size (8.5 x 11 in) paper.
    Check is located at bottom (y = 0 to check_h_in * inch).
    Voucher stub is located at y = check_h_in * inch to h_in * inch.
    """
    stub_bottom = check_h_in * inch
    stub_top = h_in * inch
    m = MARGIN_IN * inch

    c.saveState()
    # Background for voucher
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0, stub_bottom, w_in * inch, (h_in - check_h_in) * inch, fill=1, stroke=0)

    # Perforation separator line with instruction
    perf_y = stub_bottom + 4
    c.setStrokeColor(colors.HexColor("#718096"))
    c.setLineWidth(0.75)
    c.setDash(4, 4)
    c.line(m, perf_y, (w_in * inch) - m, perf_y)
    c.setDash()

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString((w_in / 2) * inch, perf_y + 8,
                        "--- DETACH HERE BEFORE CASHING OR DEPOSITING CHECK ---")

    # Voucher Header
    header_y = stub_top - 0.5 * inch
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.HexColor("#1A202C"))
    drawer_name = remittance_data.get("drawer_name", account_config.get("drawer_name", "USAA"))
    c.drawString(m, header_y, drawer_name)

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#4A5568"))
    drawer_addr_line, drawer_csz = resolve_drawer_address_lines(account_config)
    c.drawString(m, header_y - 14, drawer_addr_line)
    c.drawString(m, header_y - 26, drawer_csz)

    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(colors.HexColor("#2B6CB0"))
    c.drawRightString((w_in * inch) - m, header_y, "REMITTANCE STATEMENT")

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#2D3748"))
    raw_serial = check["serial_number"]
    pad = remittance_data.get("serial_padding", 10)
    serial_str = str(raw_serial).zfill(pad) if pad else str(raw_serial)
    c.drawRightString((w_in * inch) - m, header_y - 14, f"Check No: {serial_str}")
    c.drawRightString((w_in * inch) - m, header_y - 26, f"Issue Date: {check.get('issue_date', '')}")

    # Summary box
    summary_y = header_y - 75
    c.setStrokeColor(colors.HexColor("#CBD5E0"))
    c.setFillColor(colors.white)
    c.rect(m, summary_y, (w_in * inch) - 2 * m, 36, fill=1, stroke=1)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawString(m + 10, summary_y + 20, f"PAYEE: {check.get('payee_name', '')}")
    payee_addr_full = ", ".join(filter(None, [check.get("payee_address"), check.get("payee_city_state_zip")]))
    if payee_addr_full:
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#4A5568"))
        c.drawString(m + 10, summary_y + 8, f"ADDR: {payee_addr_full}")
    c.drawRightString((w_in * inch) - m - 10, summary_y + 20,
                      f"CHECK AMOUNT: {cents_to_courtesy(check['amount_cents'])}")

    # Details table in voucher
    tbl_y = summary_y - 120
    tbl_w = (w_in * inch) - 2 * m
    c.setFillColor(colors.HexColor("#EDF2F7"))
    c.rect(m, tbl_y + 80, tbl_w, 20, fill=1, stroke=1)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawString(m + 10, tbl_y + 86, "REFERENCE / POLICY #")
    c.drawString(m + 180, tbl_y + 86, "CLAIM / REPORT #")
    c.drawString(m + 320, tbl_y + 86, "DATE")
    c.drawRightString((w_in * inch) - m - 10, tbl_y + 86, "AMOUNT")

    c.setFillColor(colors.white)
    c.rect(m, tbl_y, tbl_w, 80, fill=1, stroke=1)

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#1A202C"))
    col1 = remittance_data.get("col1_value", "005361319")
    col2 = remittance_data.get("col2_value", "12")
    col3 = remittance_data.get("col3_value", "2023-07-22")
    c.drawString(m + 10, tbl_y + 60, col1)
    c.drawString(m + 180, tbl_y + 60, col2)
    c.drawString(m + 320, tbl_y + 60, col3)
    c.drawRightString((w_in * inch) - m - 10, tbl_y + 60, cents_to_courtesy(check['amount_cents']))

    # Explanation in voucher
    exp_text = remittance_data.get("explanation_text", "Payment under Medical Payments to Others coverage")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(m + 10, tbl_y + 35, "EXPLANATION:")
    c.setFont("Helvetica", 8)
    c.drawString(m + 90, tbl_y + 35, exp_text)

    c.restoreState()


# ---------------------------------------------------------------------------
# Reverse rendering
# ---------------------------------------------------------------------------

def _draw_reverse(c, account_config, w_in, h_in):
    """
    Draw the check reverse on the current canvas page per Regulation CC & ANSI X9.
    
    Trailing edge of check face is at left; when turned horizontally,
    the trailing edge corresponds to the RIGHT side on the back ("Back to Right").
    - Right side (trailing edge): Payee Endorsement Zone (1.7 in width)
    - Middle: Bank Endorsement Zone with 'ORIGINAL DOCUMENT' security screen backer
    - Left side: CPSA Padlock Security Features Warning Box & Reg CC notice
    """
    w_pt = w_in * inch
    h_pt = h_in * inch

    c.saveState()

    # Soft subtle backer background
    c.setFillColor(colors.HexColor("#FAFBFD"))
    c.rect(0, 0, w_pt, h_pt, fill=1, stroke=0)

    # ------------------------------------------------------------------
    # 1. MIDDLE: Security Screen Backer ('ORIGINAL DOCUMENT') & BOFD Zone
    # ------------------------------------------------------------------
    # Payee endorsement zone on the RIGHT side (trailing edge)
    endorse_w = 1.70 * inch
    endorse_x = w_pt - endorse_w
    endorse_right = w_pt - 0.20 * inch
    endorse_left = endorse_x + 0.12 * inch

    # Left warning box boundary
    warning_box_w = min(2.5 * inch, (w_in * 0.40) * inch)
    warning_box_x = 0.22 * inch

    # Bank Endorsement Zone (BOFD) is between warning box and endorsement zone
    bofd_start_x = warning_box_x + warning_box_w + 0.15 * inch
    bofd_end_x = endorse_x

    # Subtle 'ORIGINAL DOCUMENT' security pattern in bank zone
    c.saveState()
    # Clip pattern to middle zone
    p = c.beginPath()
    p.rect(bofd_start_x - 5, 0, bofd_end_x - bofd_start_x + 5, h_pt)
    c.clipPath(p, stroke=0, fill=0)

    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.setFont("Helvetica-Bold", 7.5)
    doc_text = "ORIGINAL DOCUMENT   ·   ORIGINAL DOCUMENT   ·   ORIGINAL DOCUMENT"
    step_y = 18.0
    for y_idx in range(-5, int(h_pt / step_y) + 8):
        c.saveState()
        c.translate(bofd_start_x - 40, y_idx * step_y)
        c.rotate(30)
        c.drawString(0, 0, doc_text)
        c.restoreState()
    c.restoreState()

    # BOFD boundary lines
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.75)
    c.setDash(3, 3)
    c.line(bofd_start_x, 0, bofd_start_x, h_pt)
    c.line(endorse_x, 0, endorse_x, h_pt)
    c.setDash()

    # BOFD Header Label
    c.setFont("Helvetica-Bold", 6.0)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawCentredString((bofd_start_x + bofd_end_x) / 2, h_pt - 0.20 * inch, "BANK ENDORSEMENT ZONE — DO NOT MARK")

    # ------------------------------------------------------------------
    # 2. RIGHT: Payee Endorsement Zone (Trailing Edge / Back to Right)
    # ------------------------------------------------------------------
    c.setFont("Helvetica-Bold", 8.0)
    c.setFillColor(TEXT_COLOR)
    c.drawString(endorse_left, h_pt - 0.32 * inch, "ENDORSE HERE")

    # Signature Line 1
    sig1_y = h_pt - 0.54 * inch
    c.setFont("Helvetica-Bold", 8.0)
    c.drawString(endorse_left, sig1_y + 1, "X")
    _draw_rule(c, endorse_left + 10, sig1_y, endorse_right, sig1_y)

    # Signature Line 2
    sig2_y = h_pt - 0.74 * inch
    _draw_rule(c, endorse_left + 10, sig2_y, endorse_right, sig2_y)

    # Signature Line 3
    sig3_y = h_pt - 0.94 * inch
    _draw_rule(c, endorse_left + 10, sig3_y, endorse_right, sig3_y)

    # Mobile Deposit Checkbox
    chk_y = h_pt - 1.15 * inch
    c.setStrokeColor(RULE_COLOR)
    c.setLineWidth(0.6)
    c.rect(endorse_left, chk_y, 7, 7, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(TEXT_COLOR)
    c.drawString(endorse_left + 10, chk_y + 1.5, "CHECK HERE IF MOBILE DEPOSIT")

    # Warning text
    warn_y = h_pt - 1.32 * inch
    c.setFont("Helvetica-Bold", 4.8)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawCentredString(endorse_left + (endorse_right - endorse_left) / 2, warn_y, "DO NOT WRITE, STAMP OR SIGN BELOW THIS LINE")

    # Financial Institution clear boundary line with Microprint and MP
    clear_y = h_pt - 1.45 * inch
    _draw_microprint_line(c, endorse_left, clear_y, endorse_right, clear_y)

    c.setFont("Helvetica-Bold", 4.5)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(endorse_left, clear_y - 6.5, "MP")
    c.drawRightString(endorse_right, clear_y - 6.5, "MP")
    c.drawCentredString(endorse_left + (endorse_right - endorse_left) / 2, clear_y - 6.5, "RESERVED FOR FINANCIAL INSTITUTION USE*")

    # ------------------------------------------------------------------
    # 3. LEFT: CPSA Security Features Warning Box (Image 3)
    # ------------------------------------------------------------------
    box_h = h_pt - 0.36 * inch
    box_bottom = 0.18 * inch
    c.setStrokeColor(colors.HexColor("#94A3B8"))
    c.setLineWidth(0.7)
    c.setFillColor(colors.white)
    c.rect(warning_box_x, box_bottom, warning_box_w, box_h, fill=1, stroke=1)

    # Padlock Icon in top-left of warning box
    padlock_x = warning_box_x + 8
    padlock_y = box_bottom + box_h - 18
    _draw_personal_padlock_icon(c, padlock_x, padlock_y, with_text=False)

    # Title
    c.setFont("Helvetica-Bold", 5.2)
    c.setFillColor(TEXT_COLOR)
    c.drawString(warning_box_x + 24, box_bottom + box_h - 12, "Padlock design is a certification mark")
    c.drawString(warning_box_x + 24, box_bottom + box_h - 18, "of the Check Payment Systems Association")

    # Warning Subtitle
    c.setFont("Helvetica-Bold", 5.8)
    c.drawString(warning_box_x + 8, box_bottom + box_h - 30, "Warning:")
    c.setFont("Helvetica", 4.8)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(warning_box_x + 8, box_bottom + box_h - 38, "Absence of the following Security Features may indicate alteration")

    # 4 Security Features Bullets
    items = [
        ("MP Microprint", "Tiny type on front and back fills solid when scanned or copied."),
        ("Security Pantograph", "Copy resistant security pantograph discourages duplication."),
        ("Warning Bands/Padlock", "Warn processors to be aware of detailed security features."),
        ("Security Screen Backer", "'Original Document' text & weave pattern visible on back."),
    ]
    cur_y = box_bottom + box_h - 50
    for title, desc in items:
        c.setFont("Helvetica-Bold", 5.0)
        c.setFillColor(TEXT_COLOR)
        c.drawString(warning_box_x + 8, cur_y, f"• {title}:")
        c.setFont("Helvetica", 4.6)
        c.setFillColor(colors.HexColor("#475569"))
        c.drawString(warning_box_x + 8, cur_y - 7, desc)
        cur_y -= 16

    # Federal Reserve Notice at bottom of box
    c.setFont("Helvetica-Bold", 4.6)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawCentredString(warning_box_x + warning_box_w / 2, box_bottom + 5.5, "* FEDERAL RESERVE BOARD OF GOVERNORS REG. CC")

    c.restoreState()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_rule(c, x1, y, x2, y2):
    c.setStrokeColor(RULE_COLOR)
    c.setLineWidth(0.5)
    c.line(x1, y, x2, y2)


def _draw_microprint_line(c, x1, y, x2, y2):
    """
    Draw a microprinted signature-line border.

    The text is set at 0.6pt — it reads as a solid line at normal viewing
    distance but blurs/fragments on photocopy (buildspec.md §8).
    """
    micro_text = "AUTHORIZED SIGNATURE · NOT VALID IF ALTERED · "
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 0.6)

    char_w = 0.6 * 0.6  # approximate character width at 0.6pt
    total_w = x2 - x1
    repeats = int(total_w / (len(micro_text) * char_w)) + 2
    full_text = micro_text * repeats

    # Clip to the line bounds, then draw
    c.saveState()
    # clipRect signature: clipRect(x, y, width, height)
    # No stroke/fill keyword args -- use clip=True path instead
    from reportlab.lib.units import inch as _inch
    p = c.beginPath()
    p.rect(x1, y - 1, total_w, 2)
    c.clipPath(p, stroke=0, fill=0)
    c.drawString(x1, y, full_text)
    c.restoreState()

    # Draw an actual visible line slightly above for reference
    c.setStrokeColor(TEXT_COLOR)
    c.setLineWidth(0.5)
    c.line(x1, y, x2, y2)


def _draw_pantograph(c, w_in, h_in):
    """
    Draw a very light void pantograph background.

    The word "VOID" is rendered diagonally, very pale, tiling the face.
    Stays entirely ABOVE the clear band bottom edge.
    """
    c.saveState()
    c.setFillColor(PANTOGRAPH_COLOR)
    c.setFont("Helvetica-Bold", 36)

    # Tile "VOID" diagonally across the face, above the clear band.
    safe_bottom = CLEAR_BAND_HEIGHT_IN * inch + 4  # 4pt buffer above clear band

    step_x = 2.0 * inch
    step_y = 1.5 * inch

    y = safe_bottom
    while y < h_in * inch:
        x = 0
        while x < w_in * inch:
            c.saveState()
            c.translate(x, y)
            c.rotate(35)
            c.drawString(0, 0, "VOID")
            c.restoreState()
            x += step_x
        y += step_y

    c.restoreState()


def _draw_security_legend(c, w_in, h_in):
    """Draw the security feature legend along the top edge (buildspec.md §6)."""
    legend = (
        "ORIGINAL DOCUMENT HAS COLORED BACKGROUND AND MICRO-PRINTED BORDER "
        "· ABSENCE OF THESE FEATURES INDICATES A COPY"
    )
    c.setFillColor(LEGEND_COLOR)
    c.setFont("Helvetica", 5.5)
    c.drawCentredString(
        (w_in / 2) * inch,
        (h_in - 0.12) * inch,
        legend,
    )


def _draw_padlock_icon(c, w_in, h_in):
    """
    Draw a simplified padlock icon per X9.100-170.

    X9.100-170 defines the icon; a proper implementation uses the actual
    licensed artwork. This draws a minimal geometric padlock as a placeholder.
    The security legend (§6) accompanies it.
    """
    # Position: near the bottom-right of the face, above the clear band.
    icon_x = (w_in - MARGIN_IN - 0.40) * inch
    icon_y = (CLEAR_BAND_HEIGHT_IN + 0.05) * inch
    icon_size = 0.25 * inch

    c.saveState()
    c.setStrokeColor(colors.HexColor("#4A5568"))
    c.setFillColor(colors.HexColor("#718096"))
    c.setLineWidth(1.0)

    # Shackle (arc)
    c.arc(icon_x + icon_size * 0.2, icon_y + icon_size * 0.35,
          icon_x + icon_size * 0.8, icon_y + icon_size * 1.0, 0, 180)

    # Body
    c.rect(icon_x, icon_y, icon_size, icon_size * 0.55, fill=1, stroke=1)

    # Keyhole
    c.setFillColor(BACKGROUND_COLOR)
    c.circle(icon_x + icon_size * 0.5, icon_y + icon_size * 0.35,
             icon_size * 0.12, fill=1, stroke=0)

    c.restoreState()

    # Icon label
    c.setFillColor(LEGEND_COLOR)
    c.setFont("Helvetica", 5)
    c.drawString(icon_x - 0.05 * inch, icon_y - 8, "SECURITY")
    c.drawString(icon_x - 0.05 * inch, icon_y - 15, "FEATURES")


def _draw_wrapped_text(c, text, x, y, max_width, font, font_size, color,
                       line_height=10):
    """Simple word-wrap helper for the reverse-side security warning."""
    c.setFont(font, font_size)
    c.setFillColor(color)
    words = text.split()
    line  = ""
    current_y = y

    for word in words:
        test_line = f"{line} {word}".strip()
        if c.stringWidth(test_line, font, font_size) <= max_width:
            line = test_line
        else:
            if line:
                c.drawString(x, current_y, line)
                current_y -= line_height
            line = word

    if line:
        c.drawString(x, current_y, line)
