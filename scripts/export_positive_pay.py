"""
export_positive_pay.py — Export and optionally upload the Positive Pay issue file.

Usage:
    python scripts/export_positive_pay.py [--serials 1001 1002 1003] [--all-pending]

Exports the Positive Pay issue file for the specified checks (or all pending)
and optionally uploads it to the bank.

Per buildspec.md §11: "No print run completes until the issue file is accepted
by the bank. Treat a rejected upload as a production incident."
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit
import positive_pay
import sequence

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(
        description="Export Positive Pay issue file"
    )
    parser.add_argument(
        "--serials",
        nargs="+",
        type=int,
        help="Serial numbers to include (space-separated)",
    )
    parser.add_argument(
        "--all-pending",
        action="store_true",
        help="Export all printed checks without a Positive Pay export",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output" / "positive_pay"),
        help="Output directory for the export file",
    )
    parser.add_argument(
        "--operator",
        default=getpass.getuser(),
        help="Operator ID",
    )
    parser.add_argument(
        "--db-dir",
        default=str(PROJECT_ROOT / "db"),
        help="Database directory",
    )
    args = parser.parse_args()

    if not args.serials and not args.all_pending:
        print("Error: specify --serials or --all-pending", file=sys.stderr)
        sys.exit(1)

    db_dir    = Path(args.db_dir)
    checks_db = db_dir / "checks.db"
    audit_db  = db_dir / "audit.db"

    if not checks_db.exists():
        print(f"Error: checks database not found at {checks_db}", file=sys.stderr)
        sys.exit(1)

    checks_conn = sequence.get_connection(checks_db)
    audit_conn  = audit.get_audit_connection(audit_db)

    # Load bank config
    bank_cfg = json.loads((PROJECT_ROOT / "config" / "bank_config.json").read_text())

    # Gather records
    if args.all_pending:
        records = positive_pay.check_for_unprotected_items(checks_conn)
    else:
        records = []
        for s in args.serials:
            rec = sequence.get_check_record(s, checks_conn)
            if rec is None:
                print(f"Warning: serial #{s} not found — skipping", file=sys.stderr)
            else:
                # Enrich with account_number from config
                account_cfg = json.loads(
                    (PROJECT_ROOT / "config" / "account_config.json").read_text()
                )
                rec["account_number"] = account_cfg.get("account_number", "")
                records.append(rec)

    if not records:
        print("No records to export.")
        sys.exit(0)

    print(f"Exporting {len(records)} check(s) to Positive Pay file ...")

    output_dir = Path(args.output_dir)
    file_path, sha256 = positive_pay.generate_issue_file(records, bank_cfg, output_dir)

    serials = [r["serial_number"] for r in records]
    export_id = positive_pay.register_export(file_path, sha256, serials, checks_conn)

    audit.log_event(
        audit_conn,
        "POSITIVE_PAY_EXPORTED",
        args.operator,
        file_path=str(file_path),
        sha256=sha256,
        serials=serials,
        export_id=export_id,
    )

    checks_conn.execute("COMMIT")

    print(f"✅ Positive Pay file written: {file_path}")
    print(f"   SHA-256: {sha256}")
    print(f"   Export ID: {export_id}")
    print(
        "\n⚠️  Upload this file to your bank's Positive Pay system before end of business.\n"
        "   A rejected upload is a production incident — do not leave unprotected checks overnight."
    )

    checks_conn.close()
    audit_conn.close()


if __name__ == "__main__":
    main()
