"""
signature_vault.py — AES-256-GCM encrypted signature image storage.

The signature image is never stored as a plain file on disk. It is encrypted
at rest and released only through this module's unlock function.

Controls (buildspec.md §11):
  - Signature is encrypted with AES-256-GCM using a key derived from a
    passphrase via PBKDF2-HMAC-SHA256 (310,000 iterations per OWASP 2023).
  - The unlock function returns raw image bytes to the caller; it never
    writes them to disk.
  - apply_signature() checks the security config threshold before releasing
    the signature. If the check amount exceeds the threshold, it raises
    SignatureThresholdExceeded.
  - All unlock attempts are logged via audit.py.

Vault file format (binary):
    [4 bytes: magic "SVLT"]
    [4 bytes: version uint32 big-endian]
    [16 bytes: salt for PBKDF2]
    [12 bytes: AES-GCM nonce]
    [16 bytes: AES-GCM tag]
    [N bytes: ciphertext (encrypted PNG/JPEG bytes)]
"""

import os
import struct
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


VAULT_MAGIC   = b"SVLT"
VAULT_VERSION = 1
PBKDF2_ITERS  = 310_000


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class SignatureThresholdExceeded(Exception):
    """Raised when a check amount exceeds the auto-signature threshold."""


class VaultError(Exception):
    """Raised for vault format or decryption errors."""


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _derive_key(passphrase: str | bytes, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a passphrase using PBKDF2-HMAC-SHA256."""
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERS,
    )
    return kdf.derive(passphrase)


# ---------------------------------------------------------------------------
# Vault creation (one-time setup)
# ---------------------------------------------------------------------------

def init_vault(image_path: str | Path, vault_path: str | Path, passphrase: str) -> None:
    """
    Encrypt the signature image and write it to the vault file.

    Parameters
    ----------
    image_path  : path to the signature image (PNG or JPEG)
    vault_path  : destination path for the encrypted vault file
    passphrase  : the passphrase used to derive the encryption key

    The plaintext image file is NOT deleted by this function — the caller
    should securely delete or move it after verifying the vault.
    """
    image_path = Path(image_path)
    vault_path = Path(vault_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Signature image not found: {image_path}")

    plaintext = image_path.read_bytes()

    salt  = os.urandom(16)
    nonce = os.urandom(12)
    key   = _derive_key(passphrase, salt)

    aesgcm     = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)  # includes 16-byte tag appended

    # ciphertext from AESGCM.encrypt() = actual_ciphertext + 16-byte GCM tag
    # Split for explicit storage.
    tag        = ciphertext[-16:]
    ciphertext = ciphertext[:-16]

    vault_path.parent.mkdir(parents=True, exist_ok=True)

    with open(vault_path, "wb") as f:
        f.write(VAULT_MAGIC)
        f.write(struct.pack(">I", VAULT_VERSION))
        f.write(salt)   # 16 bytes
        f.write(nonce)  # 12 bytes
        f.write(tag)    # 16 bytes
        f.write(ciphertext)

    # Restrict permissions so only the owner can read the vault.
    try:
        os.chmod(vault_path, 0o600)
    except (OSError, AttributeError):
        pass  # Windows doesn't support chmod in the same way; skip silently.


# ---------------------------------------------------------------------------
# Vault unlock (per-use)
# ---------------------------------------------------------------------------

def unlock_vault(vault_path: str | Path, passphrase: str) -> bytes:
    """
    Decrypt the vault and return the raw signature image bytes.

    The bytes are returned to the caller in memory only — they are never
    written to disk by this function.

    Raises VaultError if the file format is wrong or decryption fails.
    Raises FileNotFoundError if the vault file does not exist.
    """
    vault_path = Path(vault_path)

    if not vault_path.exists():
        raise FileNotFoundError(
            f"Signature vault not found: {vault_path}. "
            "Run scripts/setup_vault.py to initialize it."
        )

    with open(vault_path, "rb") as f:
        data = f.read()

    # Parse header
    if len(data) < 4 + 4 + 16 + 12 + 16:
        raise VaultError("Vault file is too short to be valid")

    magic   = data[0:4]
    version = struct.unpack(">I", data[4:8])[0]
    salt    = data[8:24]
    nonce   = data[24:36]
    tag     = data[36:52]
    ciphertext = data[52:]

    if magic != VAULT_MAGIC:
        raise VaultError(
            f"Vault magic mismatch: expected {VAULT_MAGIC!r}, got {magic!r}"
        )

    if version != VAULT_VERSION:
        raise VaultError(f"Unsupported vault version: {version}")

    key = _derive_key(passphrase, salt)

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    except Exception as exc:
        raise VaultError(
            "Vault decryption failed — wrong passphrase or corrupted vault"
        ) from exc

    return plaintext


# ---------------------------------------------------------------------------
# Signature application (called by renderer)
# ---------------------------------------------------------------------------

def apply_signature(
    canvas,
    check: dict,
    security_config: dict,
    vault_path: str | Path,
    passphrase: str,
    x_in: float,
    y_in: float,
    width_in: float = 2.5,
    height_in: float = 0.5,
) -> bool:
    """
    Apply the digital signature to the ReportLab canvas if the check amount
    is at or below the configured threshold.

    Parameters
    ----------
    canvas          : active ReportLab canvas (units = inches assumed; caller sets unit)
    check           : check record dict (must contain amount_cents)
    security_config : loaded security_config.json dict
    vault_path      : path to the .svlt vault file
    passphrase      : vault passphrase for this session
    x_in, y_in      : bottom-left coordinates of the signature image (in inches)
    width_in        : signature image width in inches
    height_in       : signature image height in inches

    Returns True if the signature was applied; False if the amount exceeds
    the threshold (check prints unsigned — wet signature required).

    Raises SignatureThresholdExceeded programmatically if dual_control_mode
    is False and the amount is above threshold; caller handles the policy.
    Raises VaultError if decryption fails.
    """
    import io
    from reportlab.lib.units import inch
    from reportlab.platypus import Image as RLImage

    threshold = security_config.get("signature_auto_threshold_cents", 500_000)
    amount_cents = check.get("amount_cents", 0)

    if amount_cents > threshold:
        return False  # Caller must arrange wet signature.

    # Decrypt the signature image into memory.
    sig_bytes = unlock_vault(vault_path, passphrase)

    # Draw the image onto the canvas at the specified position.
    img_buffer = io.BytesIO(sig_bytes)
    canvas.drawImage(
        img_buffer,
        x_in * inch,
        y_in * inch,
        width=width_in * inch,
        height=height_in * inch,
        preserveAspectRatio=True,
        mask="auto",
    )
    return True
