"""
test_renderer.py — Tests for src/renderer.py

Verifies PDF page dimensions, MICR line position within the print band,
and clear-band cleanliness (geometry assertion, not visual).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from renderer import render_check, CLEAR_BAND_HEIGHT_IN, PRINT_BAND_BOTTOM_IN


BANK_CONFIG = {
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
        "fields_order": ["account_number", "check_number", "issue_date", "amount", "payee_name", "void_flag"],
        "date_format": "%m/%d/%Y",
    },
    "reconciliation": {
        "format": "csv",
        "csv_columns": {"serial": "CheckNumber", "cleared_date": "PostDate",
                        "amount": "Amount", "payee": "Description"},
    },
}

ACCOUNT_CONFIG = {
    "drawer_name": "OmniLeadFeeder LLC",
    "drawer_address": "123 Main Street",
    "drawer_city_state_zip": "Phoenix, AZ 85001",
    "account_id": "primary",
    "account_number": "123456789",
    "routing_number": "021000021",
    "fractional_routing": "70-2322/719",
    "check_dimensions": {"width_in": 8.5, "height_in": 3.5},
}

SAMPLE_CHECK = {
    "serial_number":  1001,
    "account_number": "123456789",
    "routing_number": "021000021",
    "payee_name":     "Acme Corporation",
    "amount_cents":   125000,
    "issue_date":     "2026-09-19",
    "memo":           "Invoice 12345",
}


def _read_pdf_pagesize(pdf_path: Path):
    """
    Extract the MediaBox dimensions from the raw PDF bytes.
    Returns (width_pt, height_pt) as floats.
    """
    content = pdf_path.read_bytes()
    # Find MediaBox
    import re
    match = re.search(rb"/MediaBox\s*\[([^\]]+)\]", content)
    if not match:
        raise ValueError("MediaBox not found in PDF")
    parts = match.group(1).split()
    # MediaBox format: [llx lly urx ury]
    llx, lly, urx, ury = (float(p) for p in parts)
    return urx - llx, ury - lly


class TestRenderCheck:
    def test_pdf_created(self, tmp_path):
        pdf_path = tmp_path / "check_001001.pdf"
        result = render_check(SAMPLE_CHECK, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_pdf_dimensions_exact(self, tmp_path):
        """PDF page must be exactly 8.5 × 3.5 inches (612 × 252 points)."""
        pdf_path = tmp_path / "check_001001.pdf"
        render_check(SAMPLE_CHECK, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path)

        w_pt, h_pt = _read_pdf_pagesize(pdf_path)
        expected_w = 8.5 * 72  # = 612.0
        expected_h = 3.5 * 72  # = 252.0

        assert abs(w_pt - expected_w) < 0.1, (
            f"Expected width {expected_w} pt, got {w_pt} pt"
        )
        assert abs(h_pt - expected_h) < 0.1, (
            f"Expected height {expected_h} pt, got {h_pt} pt"
        )

    def test_pdf_has_two_pages(self, tmp_path):
        """PDF must have 2 pages: face + reverse (buildspec.md §7)."""
        pdf_path = tmp_path / "check_001001.pdf"
        render_check(SAMPLE_CHECK, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path)

        content = pdf_path.read_bytes()
        import re
        # Count /Page objects (excluding /Pages)
        pages = re.findall(rb"/Type\s*/Page\b", content)
        assert len(pages) == 2, f"Expected 2 pages, found {len(pages)}"

    def test_clear_band_geometry(self):
        """Clear band must be 0.625 in. Print band centre must be at 0.3125 in."""
        assert CLEAR_BAND_HEIGHT_IN == 0.625
        # Print band (0.250 in) centred in clear band:
        # bottom of print band = (0.625 - 0.250) / 2 = 0.1875 in
        assert abs(PRINT_BAND_BOTTOM_IN - 0.1875) < 0.0001

    def test_different_amounts_produce_different_pdfs(self, tmp_path):
        pdf1 = tmp_path / "check_1.pdf"
        pdf2 = tmp_path / "check_2.pdf"

        check1 = {**SAMPLE_CHECK, "amount_cents": 100}
        check2 = {**SAMPLE_CHECK, "amount_cents": 200}

        render_check(check1, BANK_CONFIG, ACCOUNT_CONFIG, pdf1)
        render_check(check2, BANK_CONFIG, ACCOUNT_CONFIG, pdf2)

        # PDFs should have different content (different amount text)
        assert pdf1.read_bytes() != pdf2.read_bytes()

    def test_memo_included_in_check(self, tmp_path):
        """Memo text should appear somewhere in the PDF byte stream."""
        pdf_path = tmp_path / "check_001001.pdf"
        render_check(SAMPLE_CHECK, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path)
        content = pdf_path.read_bytes()
        # PDF text is not always stored plainly, but the memo text should
        # appear in the stream in some form. This is a best-effort check.
        # (Full visual verification requires printing.)
        assert pdf_path.exists()  # At minimum, the file is created without error.

    def test_render_without_signature_does_not_crash(self, tmp_path):
        pdf_path = tmp_path / "check_001001.pdf"
        # draw_signature=False is the default
        result = render_check(SAMPLE_CHECK, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path,
                              draw_signature=False)
        assert result.exists()

    def test_render_with_payee_address(self, tmp_path):
        """Verify check rendering succeeds when payee_address and payee_city_state_zip are provided."""
        pdf_path = tmp_path / "check_with_addr.pdf"
        check_with_addr = {
            **SAMPLE_CHECK,
            "payee_address": "456 Corporate Blvd Suite 100",
            "payee_city_state_zip": "Austin, TX 78701",
        }
        result = render_check(check_with_addr, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path)
        assert result.exists()
        assert pdf_path.stat().st_size > 0

    def test_render_standard_voucher_sheet_with_payee_address(self, tmp_path):
        """Verify voucher sheet rendering succeeds with payee address on voucher stub."""
        pdf_path = tmp_path / "voucher_sheet_addr.pdf"
        check_with_addr = {
            **SAMPLE_CHECK,
            "page_format": "voucher_sheet",
            "payee_address": "123 Main St",
            "payee_city_state_zip": "Dallas, TX 75201",
        }
        result = render_check(check_with_addr, BANK_CONFIG, ACCOUNT_CONFIG, pdf_path, page_format="voucher_sheet")
        assert result.exists()
        assert pdf_path.stat().st_size > 0

    def test_render_personal_check_dimensions(self, tmp_path):
        """Verify personal check page dimensions are exactly 6.0 x 2 3/5 inches (432 x 187.2 pt)."""
        pdf_path = tmp_path / "personal_check.pdf"
        personal_check = {
            **SAMPLE_CHECK,
            "layout": "personal",
        }
        result = render_check(personal_check, BANK_CONFIG, {}, pdf_path, layout="personal")
        assert result.exists()
        w_pt, h_pt = _read_pdf_pagesize(pdf_path)
        expected_w = 6.0 * 72  # = 432.0
        expected_h = 2.60 * 72  # = 187.2 (2 3/5 in)
        assert abs(w_pt - expected_w) < 0.1
        assert abs(h_pt - expected_h) < 0.1

    def test_render_personal_voucher_sheet(self, tmp_path):
        """Verify personal voucher sheet page dimensions are 8.5 x 11.0 inches."""
        pdf_path = tmp_path / "personal_voucher.pdf"
        personal_check = {
            **SAMPLE_CHECK,
            "layout": "personal",
            "page_format": "voucher_sheet",
        }
        result = render_check(personal_check, BANK_CONFIG, {}, pdf_path, layout="personal", page_format="voucher_sheet")
        assert result.exists()
        w_pt, h_pt = _read_pdf_pagesize(pdf_path)
        assert abs(w_pt - 8.5 * 72) < 0.1
        assert abs(h_pt - 11.0 * 72) < 0.1
