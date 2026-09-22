"""
setup_vault.py — One-time signature vault initialization.

Run this script once to encrypt your signature image and create the
encrypted vault file at vault/signature.svlt.

Usage:
    python scripts/setup_vault.py --image path/to/signature.png

The passphrase is prompted interactively (twice for confirmation).
The original signature image is NOT deleted automatically — you must
securely delete or move it after verifying the vault.

See buildspec.md §11 and src/signature_vault.py.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Add src/ to import path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from signature_vault import init_vault, unlock_vault, VaultError

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(
        description="Initialize the chedck signature vault"
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to the signature image (PNG or JPEG)",
    )
    parser.add_argument(
        "--vault-path",
        default=str(PROJECT_ROOT / "vault" / "signature.svlt"),
        help="Output path for the vault file (default: vault/signature.svlt)",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    vault_path = Path(args.vault_path)

    if not image_path.exists():
        print(f"Error: signature image not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    if vault_path.exists():
        overwrite = input(
            f"Vault already exists at {vault_path}. Overwrite? [y/N] "
        ).strip().lower()
        if overwrite != "y":
            print("Aborted.")
            sys.exit(0)

    # Prompt for passphrase
    while True:
        passphrase = getpass.getpass("Enter vault passphrase: ")
        if len(passphrase) < 12:
            print("Passphrase must be at least 12 characters. Try again.")
            continue

        confirm = getpass.getpass("Confirm vault passphrase: ")
        if passphrase != confirm:
            print("Passphrases do not match. Try again.")
            continue

        break

    print(f"\nEncrypting {image_path} → {vault_path} ...")
    print("(This may take a few seconds — PBKDF2 key derivation)")

    init_vault(image_path, vault_path, passphrase)

    # Verify the vault
    print("Verifying vault ...")
    try:
        recovered = unlock_vault(vault_path, passphrase)
        original  = image_path.read_bytes()
        if recovered == original:
            print(f"✅ Vault verified. File: {vault_path}")
        else:
            print(
                "❌ Vault verification failed: recovered bytes do not match original.",
                file=sys.stderr,
            )
            sys.exit(1)
    except VaultError as e:
        print(f"❌ Vault verification error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"\n⚠️  IMPORTANT: The original signature image at {image_path} "
        "has NOT been deleted.\n"
        "   Securely delete it now (or move it off this machine):\n"
        f"   Windows: cipher /w:{image_path.parent} (after deleting the file)\n"
        f"   Linux:   shred -u {image_path}"
    )


if __name__ == "__main__":
    main()
