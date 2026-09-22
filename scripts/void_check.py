"""
void_check.py — CLI to void a check serial number.

Usage:
    python scripts/void_check.py --serial 1001 --reason "Printer jam" --operator ben

Marks the check as VOID in the ledger, logs to the audit trail.
Per buildspec.md §11: "Reconcile blank-stock count to serial numbers consumed
after every run. Log and shred spoilage; record it as a VOID in the ledger."
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import audit
import sequence

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(description="Void a check serial number")
    parser.add_argument("--serial",   required=True, type=int, help="Serial number to void")
    parser.add_argument("--reason",   required=True, help="Reason for voiding (required)")
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

    db_dir        = Path(args.db_dir)
    checks_db     = db_dir / "checks.db"
    audit_db      = db_dir / "audit.db"

    if not checks_db.exists():
        print(f"Error: checks database not found at {checks_db}", file=sys.stderr)
        sys.exit(1)

    checks_conn = sequence.get_connection(checks_db)
    audit_conn  = audit.get_audit_connection(audit_db)

    # Show the current record
    record = sequence.get_check_record(args.serial, checks_conn)
    if record is None:
        print(f"Error: serial #{args.serial} not found in the ledger.", file=sys.stderr)
        sys.exit(1)

    print(f"\nSerial #{args.serial}")
    print(f"  Status:   {record['status']}")
    print(f"  Payee:    {record['payee_name']}")
    print(f"  Amount:   ${record['amount_cents']/100:.2f}")
    print(f"  Date:     {record['issue_date']}")

    if record["status"] in ("cleared",):
        print(f"\nError: Cannot void a check that has already cleared the bank.", file=sys.stderr)
        sys.exit(1)

    confirm = input(
        f"\nVoid serial #{args.serial} with reason: {args.reason!r}? [y/N] "
    ).strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    try:
        checks_conn.execute("BEGIN")
        sequence.void_check(args.serial, args.reason, args.operator, checks_conn)
        checks_conn.execute("COMMIT")

        audit.log_event(
            audit_conn,
            "VOIDED",
            args.operator,
            serial=args.serial,
            reason=args.reason,
            previous_status=record["status"],
        )

        print(f"\n✅ Serial #{args.serial} voided and logged.")
        print("   ⚠️  If a physical check was printed: shred it now (P-4 cross-cut).")

    except Exception as e:
        checks_conn.execute("ROLLBACK")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        checks_conn.close()
        audit_conn.close()


if __name__ == "__main__":
    main()
