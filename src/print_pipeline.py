"""
print_pipeline.py — Main check printing orchestrator.

This is the primary entry point for the check printing system.

Pipeline (buildspec.md §10.1):

  Payment request
    → Validation
    → Sequence allocation (serial number)
    → Positive Pay issue file (SAME transaction)
    → Render PDF (1:1 scale, E-13B font)
    → Signature overlay (gated by threshold + vault passphrase)
    → [Send to printer if PRODUCTION_LOCK=LIVE]
    → Update status to 'printed'
    → Audit log

Usage:
  python print_pipeline.py [options]

  Options:
    --payee          Payee name (required)
    --amount         Amount in dollars and cents, e.g. "1250.00" (required)
    --date           Issue date YYYY-MM-DD (default: today)
    --memo           Memo line text (optional)
    --operator       Operator ID (default: current OS user)
    --printer        Printer name/ID (required in LIVE mode)
    --cartridge      Cartridge serial number (for QA tracking)
    --vault-pass     Vault passphrase for signature (prompted if omitted)
    --output-dir     Directory for PDF output (default: ./output)
    --db-dir         Directory for databases (default: ./db)

Environment:
  PRODUCTION_LOCK=LIVE   — set to actually send to the printer
                           (default: TEST — renders PDF only)
"""

import argparse
import datetime
import getpass
import json
import os
import sys
from pathlib import Path

# Add src/ to import path
sys.path.insert(0, str(Path(__file__).parent))

import audit
import positive_pay
import sequence
import validation
from amounts import parse_amount_string
from renderer import render_check
from signature_vault import apply_signature, VaultError


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


def load_config(name: str) -> dict:
    """Load a JSON config file from config/."""
    path = PROJECT_ROOT / "config" / name
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run from the project root or ensure config/ is populated."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_startup_config(
    bank_cfg: dict,
    account_cfg: dict,
    security_cfg: dict,
    audit_conn,
    operator_id: str,
) -> None:
    """
    Validate all configuration at startup. Raises ValueError on any problem.
    Logs a STARTUP audit event.
    """
    # Routing number
    rt = account_cfg.get("routing_number", "")
    validation.validate_routing_number(rt)

    # Account number
    acct = account_cfg.get("account_number", "")
    validation.validate_account_number(acct, bank_cfg)

    # Fractional routing
    frac = account_cfg.get("fractional_routing", "")
    validation.validate_fractional_routing(frac)

    # Production lock
    prod_lock = (
        security_cfg.get("production_lock", "TEST")
        or os.environ.get("PRODUCTION_LOCK", "TEST")
    ).upper()

    audit.log_event(
        audit_conn,
        "STARTUP",
        operator_id,
        production_mode=prod_lock,
        routing_number=rt,
        account_id=account_cfg.get("account_id"),
    )

    if prod_lock == "LIVE":
        print("[PRODUCTION MODE] Checks will be sent to the printer.", flush=True)
    else:
        print("[TEST MODE] PDF will be rendered to disk but not printed.", flush=True)


# ---------------------------------------------------------------------------
# Main pipeline function
# ---------------------------------------------------------------------------

def run_pipeline(
    payee: str,
    amount_cents: int,
    issue_date: str,
    memo: str,
    operator_id: str,
    printer_id: str,
    cartridge_serial: str,
    output_dir: Path,
    db_dir: Path,
    vault_passphrase: str | None,
    layout: str = "standard",
    remittance_data: dict | None = None,
    page_format: str = "check_only",
    demo_signature: bool = False,
    check_number: int | None = None,
    include_background: bool = True,
) -> dict:
    """
    Execute the full check printing pipeline for a single check.

    Returns a dict with keys:
        serial_number, pdf_path, positive_pay_export_id,
        signature_applied, status
    """
    # -- Load configs
    bank_cfg     = load_config("bank_config.json")
    account_cfg  = load_config("account_config.json")
    security_cfg = load_config("security_config.json")

    # If remittance_data supplies routing/account overrides (e.g. USAA template), apply them
    if remittance_data:
        if "routing_number" in remittance_data:
            account_cfg["routing_number"] = remittance_data["routing_number"]
        if "account_number" in remittance_data:
            account_cfg["account_number"] = remittance_data["account_number"]
        if "drawer_name" in remittance_data:
            account_cfg["drawer_name"] = remittance_data["drawer_name"]
        if "drawer_address" in remittance_data:
            account_cfg["drawer_address"] = remittance_data["drawer_address"]
        if "drawer_city_state_zip" in remittance_data:
            account_cfg["drawer_city_state_zip"] = remittance_data["drawer_city_state_zip"]
        if "fractional_routing" in remittance_data:
            account_cfg["fractional_routing"] = remittance_data["fractional_routing"]
        if "bank_name" in remittance_data:
            bank_cfg["bank_name"] = remittance_data["bank_name"]
        if "bank_city_state" in remittance_data:
            bank_cfg["bank_city_state"] = remittance_data["bank_city_state"]

    prod_lock = (
        security_cfg.get("production_lock", "TEST")
        or os.environ.get("PRODUCTION_LOCK", "TEST")
    ).upper()

    # -- Initialize databases
    db_dir.mkdir(parents=True, exist_ok=True)
    checks_db_path = db_dir / "checks.db"
    audit_db_path  = db_dir / "audit.db"

    sequence.init_db(checks_db_path)
    audit.init_audit_db(audit_db_path)

    checks_conn = sequence.get_connection(checks_db_path)
    audit_conn  = audit.get_audit_connection(audit_db_path)

    # -- Startup validation
    validate_startup_config(bank_cfg, account_cfg, security_cfg, audit_conn, operator_id)

    # -- Validate payment request
    validation.validate_payee_name(payee)
    validation.validate_amount_cents(amount_cents)

    account_id  = account_cfg.get("account_id", "primary")
    routing_num = account_cfg.get("routing_number")
    account_num = account_cfg.get("account_number")

    # -- Open print batch
    batch_id = sequence.start_print_batch(
        operator_id, printer_id, cartridge_serial, checks_conn
    )
    audit.log_event(audit_conn, "STARTUP", operator_id,
                    batch_id=batch_id, printer_id=printer_id)

    # -- BEGIN: Allocate serial + generate Positive Pay in one transaction
    serial = sequence.allocate_serial(account_id, checks_conn, requested_serial=check_number)

    sequence.populate_check_record(
        serial=serial,
        routing_number=routing_num,
        payee_name=payee,
        amount_cents=amount_cents,
        issue_date=issue_date,
        conn=checks_conn,
    )

    # Build the full check record for rendering
    check_record = {
        "serial_number":  serial,
        "account_number": account_num,
        "routing_number": routing_num,
        "payee_name":     payee,
        "amount_cents":   amount_cents,
        "issue_date":     issue_date,
        "memo":           memo,
        "layout":         layout,
        "page_format":    page_format,
        "remittance_data": remittance_data,
    }

    # Generate Positive Pay file
    pp_dir = output_dir / "positive_pay"
    try:
        pp_file, pp_hash = positive_pay.generate_issue_file(
            [check_record], bank_cfg, pp_dir
        )
        export_id = positive_pay.register_export(
            pp_file, pp_hash, [serial], checks_conn
        )
    except Exception as exc:
        # Positive Pay generation failed → roll back the whole transaction.
        checks_conn.execute("ROLLBACK")
        raise RuntimeError(
            f"Positive Pay file generation failed; transaction rolled back. "
            f"Check #{serial} was NOT allocated. Error: {exc}"
        ) from exc

    # Commit the allocation + Positive Pay registration atomically.
    checks_conn.execute("COMMIT")

    # Log allocation
    audit.log_event(audit_conn, "ALLOCATED", operator_id,
                    serial=serial, payee=payee, amount_cents=amount_cents,
                    positive_pay_export=str(pp_file))

    # -- Render the PDF
    pdf_path = output_dir / f"check_{serial:06d}.pdf"
    render_check(
        check_record, bank_cfg, account_cfg, str(pdf_path),
        draw_signature=demo_signature,
        layout=layout, remittance_data=remittance_data, page_format=page_format,
        include_background=include_background,
    )

    # -- Apply signature (if under threshold and vault available)
    sig_applied = demo_signature
    threshold   = security_cfg.get("signature_auto_threshold_cents", 500_000)

    if vault_passphrase and amount_cents <= threshold:
        vault_path = PROJECT_ROOT / "vault" / "signature.svlt"
        if vault_path.exists():
            try:
                # Re-render with signature applied
                from signature_vault import unlock_vault
                sig_bytes = unlock_vault(vault_path, vault_passphrase)
                render_check(
                    check_record, bank_cfg, account_cfg, str(pdf_path),
                    draw_signature=True, signature_image_bytes=sig_bytes,
                    layout=layout, remittance_data=remittance_data, page_format=page_format,
                    include_background=include_background,
                )
                sig_applied = True
                audit.log_event(
                    audit_conn, "SIGNATURE_RELEASED", operator_id,
                    serial=serial, amount_cents=amount_cents,
                    threshold=threshold,
                )
            except VaultError as ve:
                print(f"WARNING: Signature vault error: {ve}", file=sys.stderr)
                print("         Check will print WITHOUT digital signature.", file=sys.stderr)
        else:
            print(
                f"INFO: Signature vault not found at {vault_path}. "
                "Run scripts/setup_vault.py to initialize.",
                file=sys.stderr,
            )

    if not sig_applied and amount_cents > threshold:
        print(
            f"[INFO] Amount ${amount_cents/100:.2f} exceeds threshold "
            f"${threshold/100:.2f} - check prints UNSIGNED. "
            "Wet signature required.",
            flush=True,
        )

    sequence.update_status(
        serial, "printed", checks_conn,
        signature_applied=1 if sig_applied else 0,
        signature_approver_id=operator_id if sig_applied else None,
        print_batch_id=batch_id,
    )

    # -- Send to printer (LIVE mode only)
    if prod_lock == "LIVE":
        _send_to_printer(pdf_path, printer_id)
        print(f"[OK] Check #{serial} sent to printer: {printer_id}", flush=True)
    else:
        print(f"[TEST MODE] Check PDF rendered -> {pdf_path}", flush=True)

    # -- Finish print batch
    sequence.finish_print_batch(batch_id, checks_conn)

    audit.log_event(
        audit_conn, "PRINTED", operator_id,
        serial=serial,
        pdf_path=str(pdf_path),
        production_mode=prod_lock,
        signature_applied=sig_applied,
    )

    # -- Alert on any unprotected checks
    unprotected = positive_pay.check_for_unprotected_items(checks_conn)
    if unprotected:
        print(
            f"⚠️  ALERT: {len(unprotected)} printed check(s) have no Positive Pay export!",
            file=sys.stderr,
        )
        for u in unprotected:
            print(
                f"   Serial #{u['serial_number']}: "
                f"${u['amount_cents']/100:.2f} to {u['payee_name']}",
                file=sys.stderr,
            )

    checks_conn.close()
    audit_conn.close()

    return {
        "serial_number":          serial,
        "pdf_path":               str(pdf_path),
        "positive_pay_export_id": export_id,
        "signature_applied":      sig_applied,
        "status":                 "printed",
        "production_mode":        prod_lock,
    }


# ---------------------------------------------------------------------------
# Printer dispatch
# ---------------------------------------------------------------------------

def _send_to_printer(pdf_path: Path, printer_id: str) -> None:
    """
    Send the PDF to the physical printer.

    On Windows: uses win32api/win32print if available, falls back to
    subprocess with SumatraPDF or the default PDF viewer.
    On Linux/Mac: uses lpr.
    """
    import subprocess
    import platform

    system = platform.system()

    if system == "Windows":
        # SumatraPDF silent print (recommended for production — no dialog)
        sumatra = _find_sumatra()
        if sumatra:
            cmd = [
                sumatra,
                "-print-to", printer_id,
                "-print-settings", "noscale",  # Disable scaling — critical!
                str(pdf_path),
            ]
        else:
            # Fall back to ShellExecute print — less reliable but always present.
            import win32api
            win32api.ShellExecute(
                0, "print", str(pdf_path), f'/d:"{printer_id}"', ".", 0
            )
            return

    elif system in ("Linux", "Darwin"):
        cmd = [
            "lpr",
            "-P", printer_id,
            "-o", "scaling=100",   # Exact 1:1 scale — no fit-to-page
            "-o", "media=Letter",
            str(pdf_path),
        ]
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Printer command failed (return code {result.returncode}):\n"
            f"  stdout: {result.stdout}\n"
            f"  stderr: {result.stderr}"
        )


def _find_sumatra() -> str | None:
    """Find SumatraPDF executable on Windows."""
    candidates = [
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="chedck — In-house check printing pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--payee",      required=True, help="Payee name")
    parser.add_argument("--amount",     required=True, help='Amount, e.g. "1250.00"')
    parser.add_argument(
        "--date",
        default=datetime.date.today().isoformat(),
        help="Issue date YYYY-MM-DD (default: today)",
    )
    parser.add_argument("--memo",       default="", help="Memo line text")
    parser.add_argument(
        "--operator",
        default=getpass.getuser(),
        help="Operator ID (default: current OS user)",
    )
    parser.add_argument("--printer",    default="",  help="Printer name/ID")
    parser.add_argument("--cartridge",  default="",  help="Cartridge serial number")
    parser.add_argument("--vault-pass", default=None, help="Vault passphrase")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output"),
        help="PDF output directory",
    )
    parser.add_argument(
        "--db-dir",
        default=str(PROJECT_ROOT / "db"),
        help="Database directory",
    )
    parser.add_argument(
        "--layout",
        choices=["standard", "remittance"],
        default="standard",
        help="Check layout: 'standard' or 'remittance' (USAA/BofA voucher check)",
    )
    parser.add_argument(
        "--remittance-data",
        default=None,
        help="Path to JSON file containing remittance fields",
    )
    parser.add_argument(
        "--page-format",
        choices=["check_only", "voucher_sheet"],
        default="check_only",
        help="Page format: 'check_only' (8.5x3.5) or 'voucher_sheet' (8.5x11 letter)",
    )
    parser.add_argument(
        "--signature",
        action="store_true",
        help="Apply signature (script signature if vault passphrase not provided)",
    )

    args = parser.parse_args()

    # Parse amount
    try:
        amount_cents = parse_amount_string(args.amount)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Load remittance data if provided or if layout is remittance
    remittance_dict = None
    if args.remittance_data:
        rem_path = Path(args.remittance_data)
        if not rem_path.exists():
            print(f"Error: Remittance data file not found: {rem_path}", file=sys.stderr)
            sys.exit(1)
        with open(rem_path, encoding="utf-8") as f:
            remittance_dict = json.load(f)
    elif args.layout == "remittance":
        default_tpl = PROJECT_ROOT / "config" / "remittance_template.json"
        if default_tpl.exists():
            with open(default_tpl, encoding="utf-8") as f:
                remittance_dict = json.load(f)

    # Prompt for vault passphrase if not provided
    vault_pass = args.vault_pass
    if vault_pass is None:
        vault_path = PROJECT_ROOT / "vault" / "signature.svlt"
        if vault_path.exists():
            vault_pass = getpass.getpass("Vault passphrase (Enter to skip): ") or None

    try:
        result = run_pipeline(
            payee=args.payee,
            amount_cents=amount_cents,
            issue_date=args.date,
            memo=args.memo,
            operator_id=args.operator,
            printer_id=args.printer,
            cartridge_serial=args.cartridge,
            output_dir=Path(args.output_dir),
            db_dir=Path(args.db_dir),
            vault_passphrase=vault_pass,
            layout=args.layout,
            remittance_data=remittance_dict,
            page_format=args.page_format,
            demo_signature=args.signature,
        )
        print(f"\nResult: {result}")
    except Exception as exc:
        print(f"\n[ERROR] Pipeline error: {exc}", file=sys.stderr)
        sys.exit(1)



if __name__ == "__main__":
    main()
