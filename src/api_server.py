"""
api_server.py — FastAPI backend for the Check Printing Web UI.

Provides REST endpoints for:
- Accounts and bank configuration
- Real-time check preview rendering (using ReportLab + pypdfium2)
- Check issuance & atomic Positive Pay allocation
- Issued check history and void management
- Serving generated check PDFs
"""

import base64
import datetime
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure src/ is on Python path
SRC_DIR = Path(__file__).parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import amounts
import audit
import micr
import pypdfium2 as pdfium
import sequence
import validation
from print_pipeline import load_config, run_pipeline
from renderer import render_check

app = FastAPI(
    title="Check Engine API",
    description="ANSI X9.100 Check Printing & Remittance Voucher Engine API",
    version="1.0.0",
)

# Enable CORS for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = PROJECT_ROOT / "output"
DB_DIR = PROJECT_ROOT / "db"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# Mount generated output directory for direct PDF viewing / printing
app.mount("/api/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


ACCOUNT_OVERRIDE_FIELDS = {
    "routing_number",
    "account_number",
    "drawer_name",
    "drawer_address",
    "drawer_city_state_zip",
    "drawer_address_line1",
    "drawer_address_line2",
    "drawer_city",
    "drawer_state_province",
    "drawer_postal_code",
    "drawer_country",
    "fractional_routing",
}

BANK_OVERRIDE_FIELDS = {
    "bank_name",
    "bank_city_state",
}


def _apply_account_bank_overrides(account_cfg: dict, bank_cfg: dict, overrides: Optional[Dict[str, Any]]) -> None:
    if not overrides:
        return
    for key, value in overrides.items():
        if value is None:
            continue
        if key in ACCOUNT_OVERRIDE_FIELDS:
            account_cfg[key] = value
        if key in BANK_OVERRIDE_FIELDS:
            bank_cfg[key] = value


def _build_request_overrides(req: Any) -> dict:
    overrides = {}
    for field in ACCOUNT_OVERRIDE_FIELDS | BANK_OVERRIDE_FIELDS:
        if hasattr(req, field):
            value = getattr(req, field)
            if value is not None:
                overrides[field] = value
    return overrides


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------

class RemittanceDataModel(BaseModel):
    document_control_left: Optional[str] = "500489-1221"
    retention_notice: Optional[str] = "RETAIN THE TOP PORTION FOR YOUR RECORDS"
    document_control_right: Optional[str] = "136366-0520"
    security_bar_text: Optional[str] = (
        "FACE OF DOCUMENT HAS A COLORED BACKGROUND. THE BACK CONTAINS AN ARTIFICIAL WATERMARK. HOLD AT ANGLE TO VIEW."
    )
    security_bar_color: Optional[str] = "#342268"
    drawer_name: Optional[str] = "USAA"
    drawer_address: Optional[str] = "9800 Fredericksburg Rd"
    drawer_city_state_zip: Optional[str] = "San Antonio TX 78288"
    bank_name: Optional[str] = "Bank of America"
    bank_city_state: Optional[str] = "Hartford,CT"
    fractional_routing: Optional[str] = "51-44/119 CT"
    routing_number: Optional[str] = "011900445"
    account_number: Optional[str] = "007740015665"
    line_of_business: Optional[str] = "LOB: P&C"
    expiration_notice: Optional[str] = "VOID 180 DAYS FROM ISSUE DATE"
    payment_explanation_label: Optional[str] = "PAYMENT EXPLANATION:"
    payment_explanation_text: Optional[str] = "Payment under Medical Payments to Others coverage"
    signature_title: Optional[str] = "Authorized Signature"
    signature_text: Optional[str] = "Minnie Hinds"
    claim_fields: Optional[List[Dict[str, str]]] = [
        {"label": "USAA #", "value": "005361319"},
        {"label": "LOSS RPT #", "value": "12"},
        {"label": "LOSS DATE", "value": "2023-07-22"},
        {"label": "POLICYHOLDER", "value": "JAMES L GRASS"},
    ]


class PreviewRequest(BaseModel):
    account_id: Optional[str] = "ACC-001"
    check_number: Optional[int] = None
    payee: str = "BRANDON BACH"
    payee_address: Optional[str] = None
    payee_city_state_zip: Optional[str] = None
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    amount_dollars: float = 5000.00
    issue_date: Optional[str] = None
    memo: Optional[str] = "Medical Payments to Others coverage"
    layout: str = "remittance"  # "standard" or "remittance"
    page_format: str = "check_only"  # "check_only" or "voucher_sheet"
    signature_name: Optional[str] = "Minnie Hinds"
    draw_signature: bool = True
    remittance_data: Optional[Dict[str, Any]] = None
    outline_only: bool = False
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    drawer_name: Optional[str] = None
    drawer_address: Optional[str] = None
    drawer_city_state_zip: Optional[str] = None
    drawer_address_line1: Optional[str] = None
    drawer_address_line2: Optional[str] = None
    drawer_city: Optional[str] = None
    drawer_state_province: Optional[str] = None
    drawer_postal_code: Optional[str] = None
    drawer_country: Optional[str] = None
    fractional_routing: Optional[str] = None


class PrintRequest(BaseModel):
    account_id: Optional[str] = "ACC-001"
    check_number: Optional[int] = None
    payee: str
    payee_address: Optional[str] = None
    payee_city_state_zip: Optional[str] = None
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    amount_dollars: float
    issue_date: Optional[str] = None
    memo: Optional[str] = ""
    operator_id: Optional[str] = "web_operator"
    printer_id: Optional[str] = "PDF_ONLY"
    cartridge_serial: Optional[str] = "QA-WEB-001"
    layout: str = "standard"
    page_format: str = "check_only"
    signature_name: Optional[str] = None
    remittance_data: Optional[Dict[str, Any]] = None
    outline_only: bool = False
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    drawer_name: Optional[str] = None
    drawer_address: Optional[str] = None
    drawer_city_state_zip: Optional[str] = None
    drawer_address_line1: Optional[str] = None
    drawer_address_line2: Optional[str] = None
    drawer_city: Optional[str] = None
    drawer_state_province: Optional[str] = None
    drawer_postal_code: Optional[str] = None
    drawer_country: Optional[str] = None
    fractional_routing: Optional[str] = None


class VoidRequest(BaseModel):
    reason: str
    operator_id: Optional[str] = "web_operator"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def get_health():
    return {"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


@app.get("/api/accounts")
def get_accounts():
    """Return configured accounts and system mode."""
    acct_cfg = load_config("account_config.json")
    bank_cfg = load_config("bank_config.json")
    sec_cfg = load_config("security_config.json")

    # Mode from config or env
    mode = (sec_cfg.get("production_lock") or os.environ.get("PRODUCTION_LOCK", "TEST")).upper()

    return {
        "production_lock": mode,
        "accounts": [
            {
                "account_id": acct_cfg.get("account_id", "ACC-001"),
                "bank_name": bank_cfg.get("bank_name", "Primary Bank"),
                "bank_city_state": bank_cfg.get("bank_city_state", "Charlotte, NC"),
                "drawer_name": acct_cfg.get("drawer_name", "Acme Corporation"),
                "drawer_address": acct_cfg.get("drawer_address", "100 Enterprise Way"),
                "drawer_city_state_zip": acct_cfg.get("drawer_city_state_zip", "Austin, TX 78701"),
                "drawer_address_line1": acct_cfg.get("drawer_address_line1"),
                "drawer_address_line2": acct_cfg.get("drawer_address_line2"),
                "drawer_city": acct_cfg.get("drawer_city"),
                "drawer_state_province": acct_cfg.get("drawer_state_province"),
                "drawer_postal_code": acct_cfg.get("drawer_postal_code"),
                "drawer_country": acct_cfg.get("drawer_country"),
                "routing_number": acct_cfg.get("routing_number", "053000196"),
                "account_number": acct_cfg.get("account_number", "123456789012"),
                "routing_number_masked": validation.mask_sensitive_number(
                    str(acct_cfg.get("routing_number", "053000196"))
                ),
                "account_number_masked": validation.mask_sensitive_number(
                    str(acct_cfg.get("account_number", "123456789012"))
                ),
                "fractional_routing": acct_cfg.get("fractional_routing", "68-19/530"),
            }
        ],
    }


@app.get("/api/templates/remittance")
def get_remittance_template():
    """Return the default USAA Remittance template."""
    return load_config("remittance_template.json")


class AccountConfigUpdate(BaseModel):
    drawer_name: str
    drawer_address: Optional[str] = ""
    drawer_city_state_zip: Optional[str] = ""
    drawer_address_line1: Optional[str] = None
    drawer_address_line2: Optional[str] = None
    drawer_city: Optional[str] = None
    drawer_state_province: Optional[str] = None
    drawer_postal_code: Optional[str] = None
    drawer_country: Optional[str] = None
    account_number: str
    routing_number: str
    fractional_routing: str


@app.post("/api/config/account")
def update_account_config(req: AccountConfigUpdate):
    """Save updated account and routing number to config/account_config.json."""
    import validation as v

    # Validate routing number
    try:
        normalized_routing = v.normalize_numeric_identifier(req.routing_number, "Routing number")
        v.validate_routing_number(normalized_routing)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Routing number invalid: {e}")

    # Validate account number (pass bank_config for max-width from bank spec)
    bank_cfg_for_validation = load_config("bank_config.json")
    try:
        normalized_account = v.normalize_numeric_identifier(req.account_number, "Account number")
        v.validate_account_number(normalized_account, bank_cfg_for_validation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Account number invalid: {e}")

    # Load existing config to preserve non-editable fields
    cfg_path = CONFIG_DIR / "account_config.json"
    existing = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}

    city = (req.drawer_city or "").strip()
    state = (req.drawer_state_province or "").strip()
    postal = (req.drawer_postal_code or "").strip()
    country = (req.drawer_country or "").strip()
    city_state = ", ".join(part for part in [city, state] if part)
    if city_state and postal:
        city_state_zip = f"{city_state} {postal}"
    else:
        city_state_zip = city_state or postal
    if country:
        city_state_zip = f"{city_state_zip} · {country}" if city_state_zip else country

    existing.update({
        "drawer_name": req.drawer_name,
        "drawer_address": req.drawer_address_line1 or req.drawer_address or "",
        "drawer_city_state_zip": city_state_zip or req.drawer_city_state_zip or "",
        "drawer_address_line1": req.drawer_address_line1,
        "drawer_address_line2": req.drawer_address_line2,
        "drawer_city": req.drawer_city,
        "drawer_state_province": req.drawer_state_province,
        "drawer_postal_code": req.drawer_postal_code,
        "drawer_country": req.drawer_country,
        "account_number": normalized_account,
        "routing_number": normalized_routing,
        "fractional_routing": req.fractional_routing,
    })

    cfg_path.write_text(json.dumps(existing, indent=2))

    return {
        "success": True,
        "message": "Account configuration updated successfully.",
        "routing_number_masked": v.mask_sensitive_number(normalized_routing),
        "account_number_masked": v.mask_sensitive_number(normalized_account),
    }


@app.get("/api/checks")
def get_checks(limit: int = 50):
    """Fetch issued check records from SQLite database."""
    checks_db_path = DB_DIR / "checks.db"
    if not checks_db_path.exists():
        sequence.init_db(checks_db_path)

    conn = sequence.get_connection(checks_db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            c.serial_number,
            c.account_id,
            c.routing_number,
            c.payee_name,
            c.amount_cents,
            c.issue_date,
            c.status,
            c.created_at,
            c.updated_at,
            c.signature_applied,
            e.file_path
        FROM checks c
        LEFT JOIN positive_pay_exports e ON c.positive_pay_export_id = e.id
        ORDER BY c.serial_number DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()

    checks = []
    for r in rows:
        serial = r["serial_number"]
        pdf_file = f"check_{serial:06d}.pdf"
        has_pdf = (OUTPUT_DIR / pdf_file).exists()
        checks.append({
            "serial_number": serial,
            "account_id": r["account_id"],
            "routing_number_masked": validation.mask_sensitive_number(str(r["routing_number"] or "")),
            "payee_name": r["payee_name"],
            "amount_cents": r["amount_cents"],
            "amount_formatted": f"${r['amount_cents'] / 100:,.2f}",
            "issue_date": r["issue_date"],
            "status": r["status"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "signature_applied": bool(r["signature_applied"]),
            "pdf_url": f"/api/output/{pdf_file}" if has_pdf else None,
            "positive_pay_file": Path(r["file_path"]).name if r["file_path"] else None,
        })
    return {"checks": checks}


@app.get("/api/checks/next-serial")
def get_next_serial_endpoint():
    """Return the next available sequential check number from the ledger without advancing."""
    checks_db_path = DB_DIR / "checks.db"
    if not checks_db_path.exists():
        sequence.init_db(checks_db_path)
    conn = sequence.get_connection(checks_db_path)
    next_serial = sequence.get_next_serial(conn)
    return {"next_serial": next_serial}


@app.post("/api/checks/preview")
def preview_check(req: PreviewRequest):
    """
    Dynamically renders a check to an in-memory PDF, then converts
    Page 1 to high-resolution PNG bytes using pypdfium2.
    Returns base64 data URL, formatted amount strings, and dynamic MICR line.
    """
    bank_cfg = load_config("bank_config.json")
    account_cfg = load_config("account_config.json")

    amount_cents = int(round(req.amount_dollars * 100))
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")

    issue_date = req.issue_date or datetime.date.today().strftime("%Y-%m-%d")

    # Apply template overrides if remittance layout
    remittance_data = req.remittance_data
    if req.layout == "remittance" and not remittance_data:
        remittance_data = load_config("remittance_template.json")
    request_overrides = _build_request_overrides(req)
    if request_overrides:
        remittance_data = {**(remittance_data or {}), **request_overrides}

    _apply_account_bank_overrides(account_cfg, bank_cfg, remittance_data)
    _apply_account_bank_overrides(account_cfg, bank_cfg, _build_request_overrides(req))

    try:
        validation.validate_routing_number(str(account_cfg.get("routing_number", "")))
        validation.validate_account_number(str(account_cfg.get("account_number", "")), bank_cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Apply routing / account overrides
    if req.routing_number:
        account_cfg["routing_number"] = req.routing_number
    if req.account_number:
        account_cfg["account_number"] = req.account_number

    checks_db_path = DB_DIR / "checks.db"
    if not checks_db_path.exists():
        sequence.init_db(checks_db_path)
    conn = sequence.get_connection(checks_db_path)

    # Determine dynamic check serial number
    if req.check_number is not None and req.check_number > 0:
        serial = req.check_number
    else:
        if req.layout == "remittance":
            serial = 39254225
        else:
            serial = sequence.get_next_serial(conn)

    # Format serial string per layout padding
    if req.layout == "remittance" and remittance_data:
        pad = remittance_data.get("serial_padding", 10)
        serial_str = str(serial).zfill(pad) if pad else str(serial)
    else:
        pad = bank_cfg.get("micr_fields", {}).get("auxiliary_on_us", {}).get("zero_pad", 0)
        serial_str = str(serial).zfill(pad) if pad else str(serial)

    check_record = {
        "serial_number":        serial,
        "account_number":       account_cfg.get("account_number", "007740015665"),
        "routing_number":       account_cfg.get("routing_number", "011900445"),
        "payee_name":           req.payee,
        "payee_address":        req.payee_address,
        "payee_city_state_zip": req.payee_city_state_zip,
        "amount_cents":         amount_cents,
        "issue_date":           issue_date,
        "memo":                 req.memo or "",
        "layout":               req.layout,
        "page_format":          req.page_format,
        "remittance_data":      remittance_data,
    }

    try:
        pdf_buf = io.BytesIO()
        render_check(
            check_record,
            bank_cfg,
            account_cfg,
            pdf_buf,
            draw_signature=req.draw_signature,
            layout=req.layout,
            remittance_data=remittance_data,
            page_format=req.page_format,
            include_background=not req.outline_only,
        )

        pdf_bytes = pdf_buf.getvalue()
        pdf = pdfium.PdfDocument(pdf_bytes)
        page = pdf[0]
        # Render at 150 DPI (scale 2.0)
        pil_img = page.render(scale=2.0).to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", optimize=True)
        img_bytes = buf.getvalue()
        b64_img = base64.b64encode(img_bytes).decode("ascii")

        b64_back_img = None
        if len(pdf) > 1:
            back_page = pdf[1]
            back_pil = back_page.render(scale=2.0).to_pil()
            back_buf = io.BytesIO()
            back_pil.save(back_buf, format="PNG", optimize=True)
            b64_back_img = base64.b64encode(back_buf.getvalue()).decode("ascii")
        pdf.close()

        # Computed amount words
        if req.layout == "remittance":
            legal_text = amounts.cents_to_remittance_legal(amount_cents)
            courtesy_text = amounts.cents_to_remittance_courtesy(amount_cents)
        else:
            legal_text = amounts.cents_to_legal(amount_cents)
            courtesy_text = amounts.cents_to_courtesy(amount_cents)

        # Compute dynamic MICR display string directly from authentic E-13B codeline
        raw_code_line = micr.build_code_line(check_record, bank_cfg)
        micr_display = raw_code_line.replace(micr.TRANSIT, "T").replace(micr.ON_US, "O").replace(micr.AMOUNT, "A").strip()

        return {
            "image_data_url": f"data:image/png;base64,{b64_img}",
            "back_image_data_url": f"data:image/png;base64,{b64_back_img}" if b64_back_img else None,
            "amount_cents": amount_cents,
            "legal_text": legal_text,
            "courtesy_text": courtesy_text,
            "page_format": req.page_format,
            "layout": req.layout,
            "serial_number": serial,
            "serial_formatted": serial_str,
            "micr_display": micr_display,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")


@app.post("/api/checks/print")
def print_check_endpoint(req: PrintRequest):
    """
    Executes the official check pipeline:
    - Atomically allocates sequence serial number (or validates requested serial)
    - Generates matching Positive Pay record
    - Renders official production PDF
    - Logs audit trail
    """
    amount_cents = int(round(req.amount_dollars * 100))
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")

    issue_date = req.issue_date or datetime.date.today().strftime("%Y-%m-%d")

    remittance_data = req.remittance_data
    if req.layout == "remittance" and not remittance_data:
        remittance_data = load_config("remittance_template.json")

    try:
        result = run_pipeline(
            payee=req.payee,
            amount_cents=amount_cents,
            issue_date=issue_date,
            memo=req.memo or "",
            operator_id=req.operator_id or "web_operator",
            printer_id=req.printer_id or "PDF_ONLY",
            cartridge_serial=req.cartridge_serial or "QA-WEB-001",
            output_dir=OUTPUT_DIR,
            db_dir=DB_DIR,
            vault_passphrase=None,
            layout=req.layout,
            remittance_data=remittance_data,
            page_format=req.page_format,
            demo_signature=True,
            check_number=req.check_number,
            include_background=not req.outline_only,
            payee_address=req.payee_address,
            payee_city_state_zip=req.payee_city_state_zip,
            routing_number=req.routing_number,
            account_number=req.account_number,
        )

        serial = result["serial_number"]
        pdf_filename = f"check_{serial:06d}.pdf"

        return {
            "success": True,
            "serial_number": serial,
            "status": result["status"],
            "pdf_url": f"/api/output/{pdf_filename}",
            "signature_applied": result["signature_applied"],
            "positive_pay_export_id": result["positive_pay_export_id"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check issuance failed: {str(e)}")


@app.post("/api/checks/{serial}/void")
def void_check_endpoint(serial: int, req: VoidRequest):
    """Void an issued check and record audit event."""
    checks_db_path = DB_DIR / "checks.db"
    audit_db_path = DB_DIR / "audit.db"

    checks_conn = sequence.get_connection(checks_db_path)
    audit_conn = audit.get_audit_connection(audit_db_path)

    try:
        sequence.void_check(
            serial=serial,
            reason=req.reason,
            operator_id=req.operator_id or "web_operator",
            conn=checks_conn,
        )
        audit.log_event(
            audit_conn,
            "VOIDED",
            req.operator_id or "web_operator",
            serial=serial,
            reason=req.reason,
        )
        return {"success": True, "serial": serial, "status": "voided"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to void check #{serial}: {str(e)}")


# ---------------------------------------------------------------------------
# Static Frontend Serving (Single-Port Production Deployment)
# ---------------------------------------------------------------------------

class SPAStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1000})
            return
        await super().__call__(scope, receive, send)


UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"
if UI_DIST_DIR.is_dir() and (UI_DIST_DIR / "index.html").exists():
    app.mount("/", SPAStaticFiles(directory=str(UI_DIST_DIR), html=True), name="static_ui")
