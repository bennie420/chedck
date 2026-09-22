"""
load_recon.py — CLI to ingest a bank reconciliation file.

Usage:
    python scripts/load_recon.py --file path/to/recon.csv

Parses the bank's daily reconciliation file, matches each cleared item
against the check ledger, and prints a summary of matches and mismatches.

Per buildspec.md §10.2 (UCC §4-406 duty):
  "Ingest your bank's reconciliation/BAI2 file daily and auto-compare
   cleared amount, payee, and serial against the issue record."
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit
import reconciliation
import sequence

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a bank reconciliation file"
    )
    parser.add_argument("--file",     required=True, help="Path to the reconciliation file")
    parser.add_argument(
        "--operator",
        default=getpass.getuser(),
        help="Operator ID (default: current OS user)",
    )
    parser.add_argument(
        "--db-dir",
        default=str(PROJECT_ROOT / "db"),
        help="Database directory",
    )
    args = parser.parse_args()

    recon_file = Path(args.file)
    if not recon_file.exists():
        print(f"Error: reconciliation file not found: {recon_file}", file=sys.stderr)
        sys.exit(1)

    db_dir    = Path(args.db_dir)
    checks_db = db_dir / "checks.db"
    audit_db  = db_dir / "audit.db"

    if not checks_db.exists():
        print(f"Error: checks database not found at {checks_db}", file=sys.stderr)
        sys.exit(1)

    bank_cfg    = json.loads((PROJECT_ROOT / "config" / "bank_config.json").read_text())
    checks_conn = sequence.get_connection(checks_db)
    audit_conn  = audit.get_audit_connection(audit_db)

    print(f"Loading reconciliation file: {recon_file}")
    try:
        cleared_items = reconciliation.load_recon_file(recon_file, bank_cfg)
    except Exception as e:
        print(f"Error loading file: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(cleared_items)} transaction(s). Running reconciliation ...")

    checks_conn.execute("BEGIN")
    try:
        result = reconciliation.reconcile(
            cleared_items, checks_conn, audit_conn, args.operator
        )
        checks_conn.execute("COMMIT")
    except Exception as e:
        checks_conn.execute("ROLLBACK")
        print(f"Reconciliation error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n✅ Matched (clean):   {result['matched']}")
    print(f"⚠️  Mismatches:       {len(result['mismatches'])}")
    print(f"❓  Unknown serials:  {len(result['unknown_serials'])}")

    if result["mismatches"]:
        print("\n--- MISMATCHES (investigate immediately) ---")
        for m in result["mismatches"]:
            print(
                f"  Serial #{m.get('serial','?')}: "
                f"{m.get('mismatch_reason','?')}  |  "
                f"Cleared: ${m.get('cleared_amount_cents',0)/100:.2f}"
            )

    if result["unknown_serials"]:
        print("\n--- UNKNOWN SERIALS (possible counterfeits) ---")
        for s in result["unknown_serials"]:
            print(f"  Serial #{s}")

    if result["mismatches"] or result["unknown_serials"]:
        print("\n⚠️  ACTION REQUIRED: Contact your bank immediately about the items above.")
        sys.exit(2)  # Non-zero exit signals the calling process/scheduler.

    checks_conn.close()
    audit_conn.close()


if __name__ == "__main__":
    main()
