"""
test_remittance_renderer.py — Unit tests for remittance / voucher check layout.
Verifies PDF geometry, remittance elements, courtesy and legal formatting,
and multi-format page sizes (check-only and 8.5x11 voucher sheet).
"""

import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from renderer import render_check, CLEAR_BAND_HEIGHT_IN
from amounts import cents_to_remittance_courtesy, cents_to_remittance_legal
from micr import build_code_line, validate_code_line


BANK_CONFIG = {
    "bank_name": "Bank of America",
    "bank_city_state": "Hartford,CT",
    "micr_fields": {
        "amount_field":     {"start": 1,  "end": 12},
        "amount_separator": {"position": 13},
        "on_us_field":      {"start": 14, "end": 31, "left_delimiter": False},
        "on_us_separator":  {"position": 32},
        "routing_field":    {"start": 33, "end": 43},
        "epc_field":        {"position": 44, "use": False, "value": ""},
        "auxiliary_on_us":  {
            "start": 45, "end": 65,
            "tight_delimiters": True,
            "zero_pad": 10,
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
    "drawer_name": "USAA",
    "drawer_address": "9800 Fredericksburg Rd",
    "drawer_city_state_zip": "San Antonio TX 78288",
    "account_id": "usaa_claims",
    "account_number": "007740015665",
    "routing_number": "011900445",
    "fractional_routing": "51-44/119 CT",
    "check_dimensions": {"width_in": 8.5, "height_in": 3.5},
}

REMITTANCE_DATA = {
    "voucher_header_text": "RETAIN THE TOP PORTION FOR YOUR RECORDS",
    "control_number_left": "500489-1221",
    "control_number_right": "136366-0520",
    "security_bar_text": "FACE OF DOCUMENT HAS A COLORED BACKGROUND. THE BACK CONTAINS AN ARTIFICIAL WATERMARK. HOLD AT ANGLE TO VIEW.",
    "drawer_name": "USAA",
    "drawer_address": "9800 Fredericksburg Rd",
    "drawer_city_state_zip": "San Antonio TX 78288",
    "bank_name": "Bank of America",
    "bank_city_state": "Hartford,CT",
    "fractional_routing": "51-44/119 CT",
    "routing_number": "011900445",
    "account_number": "007740015665",
    "serial_padding": 10,
    "line_of_business": "LOB: P&C",
    "col1_header": "USAA #",
    "col1_value": "005361319",
    "col2_header": "LOSS RPT #",
    "col2_value": "12",
    "col3_header": "LOSS DATE",
    "col3_value": "2023-07-22",
    "col4_header": "POLICYHOLDER",
    "col4_value": "JAMES L GRASS",
    "explanation_title": "PAYMENT EXPLANATION:",
    "explanation_text": "Payment under Medical Payments to Others coverage",
    "stale_date_text": "VOID 180 DAYS FROM ISSUE DATE",
    "signature_name": "Minnie Hinds",
}

SAMPLE_CHECK = {
    "serial_number": 39254225,
    "account_number": "007740015665",
    "routing_number": "011900445",
    "payee_name": "BRANDON BACH",
    "amount_cents": 500000,
    "issue_date": "2024-03-25",
    "memo": "Medical Payments to Others",
}


def _read_pdf_pagesize(pdf_path: Path):
    content = pdf_path.read_bytes()
    match = re.search(rb"/MediaBox\s*\[([^\]]+)\]", content)
    if not match:
        raise ValueError("MediaBox not found in PDF")
    parts = match.group(1).split()
    llx, lly, urx, ury = (float(p) for p in parts)
    return urx - llx, ury - lly


class TestRemittanceAmounts:
    def test_courtesy_format(self):
        courtesy = cents_to_remittance_courtesy(500000)
        assert courtesy == "$**5,000.00"

    def test_legal_format_exact_match(self):
        legal = cents_to_remittance_legal(500000)
        assert legal == "**FIVE THOUSAND AND XX/100 DOLLAR**"

    def test_legal_format_with_cents(self):
        legal = cents_to_remittance_legal(125035)
        assert legal == "**ONE THOUSAND TWO HUNDRED FIFTY AND 35/100 DOLLAR**"


class TestRemittanceRenderer:
    def test_render_check_only_dimensions(self, tmp_path):
        pdf_path = tmp_path / "remittance_check.pdf"
        render_check(
            SAMPLE_CHECK,
            BANK_CONFIG,
            ACCOUNT_CONFIG,
            pdf_path,
            draw_signature=True,
            layout="remittance",
            remittance_data=REMITTANCE_DATA,
            page_format="check_only",
        )
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

        w_pt, h_pt = _read_pdf_pagesize(pdf_path)
        assert abs(w_pt - 8.5 * 72) < 0.1
        assert abs(h_pt - 3.5 * 72) < 0.1

    def test_render_voucher_sheet_dimensions(self, tmp_path):
        pdf_path = tmp_path / "remittance_voucher_sheet.pdf"
        render_check(
            SAMPLE_CHECK,
            BANK_CONFIG,
            ACCOUNT_CONFIG,
            pdf_path,
            draw_signature=True,
            layout="remittance",
            remittance_data=REMITTANCE_DATA,
            page_format="voucher_sheet",
        )
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

        w_pt, h_pt = _read_pdf_pagesize(pdf_path)
        assert abs(w_pt - 8.5 * 72) < 0.1
        assert abs(h_pt - 11.0 * 72) < 0.1

    def test_micr_line_for_remittance_check(self):
        check = {**SAMPLE_CHECK, "serial_padding": 10}
        line = build_code_line(check, BANK_CONFIG)
        assert len(line) == 65
        warnings = validate_code_line(line)
        assert len(warnings) == 0
        # Check that routing digits and serial digits are present in scanner order (R-to-L)
        scanner_order = line[::-1]
        assert "011900445" in scanner_order
        assert "0039254225" in scanner_order
