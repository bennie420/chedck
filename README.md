                                                                             # chedck — In-House Check Printing System

**OmniLeadFeeder · Build v1.0 · September 2026**

A self-contained, production-quality check printing system built to the
requirements in [buildspec.md](buildspec.md). Replaces a dedicated
check-printer appliance; prints on your own account using your own equipment.

---

## ⚠️ Before You Print Live Stock

1. **Purchase the X9.100 standards** — the [X9.100 Core Check Printer Package](https://webstore.ansi.org/SDO/x9) (~$250) plus TR-6 and TR-8. This code is a summary; the standards are the controlling text.
2. **Request your bank's MICR spec form** (X9.100-161 form). Fill in `config/bank_config.json` with the exact On-Us and Auxiliary On-Us field positions for your account.
3. **Procure hardware** per [buildspec.md §9](buildspec.md#9-hardware-bill-of-materials).
4. **Send the 20-sample test deck** to your bank's MICR quality lab and wait for written approval before setting `PRODUCTION_LOCK=LIVE`.

---

## Quick Start

### 1. Install Python dependencies

```powershell
cd c:\Users\ben\chedck
python -m pip install -r requirements.txt
```

### 2. Configure your account

Edit the three config files in `config/`:

| File | What to fill in |
|---|---|
| `config/bank_config.json` | Bank MICR field map (get from bank's spec form), Positive Pay format |
| `config/account_config.json` | Your routing number, account number, fractional routing, drawer name |
| `config/security_config.json` | Signature threshold, production lock |

> **Routing number validation** runs at startup. The placeholder `000000000` will be rejected until you set the real value.

### 3. Run the test suite

```powershell
python -m pytest tests/ -v
```

All tests must pass before printing.

### 4. Initialize the signature vault (optional)

```powershell
python scripts/setup_vault.py --image path\to\your\signature.png
```

The signature image is encrypted with AES-256-GCM. The passphrase is prompted interactively. After verifying the vault, securely delete the original image file.

### 5. Print a test check (TEST mode — no printer required)

```powershell
python src\print_pipeline.py --payee "Acme Corporation" --amount "1250.00" --memo "Invoice 12345"
```

The PDF renders to `output/check_001001.pdf`. Open it and measure:
- Page size: exactly **8.5 × 3.5 inches**
- MICR line: in the print band (centred at 0.3125 in from the bottom edge)
- Clear band (bottom 0.625 in): **nothing but MICR characters**

### 6. Go live (after bank approval)

Set the environment variable:

```powershell
$env:PRODUCTION_LOCK = "LIVE"
python src\print_pipeline.py --payee "Acme Corporation" --amount "1250.00" --printer "YourPrinterName"
```

Or set `"production_lock": "LIVE"` in `config/security_config.json`.

---

## Daily Operations

### Print a check

```powershell
python src\print_pipeline.py `
  --payee "Vendor Name" `
  --amount "500.00" `
  --memo "Invoice 9999" `
  --printer "HP-LaserJet-MICR" `
  --cartridge "CART-2026-001"
```

### Void a check

```powershell
python scripts\void_check.py --serial 1001 --reason "Printer jam — destroyed"
```

Then **shred the physical check** (P-4 cross-cut minimum).

### Export Positive Pay file

After every print run:

```powershell
python scripts\export_positive_pay.py --all-pending
```

Upload the generated CSV to your bank's Positive Pay portal before end of business.

### Reconcile daily

```powershell
python scripts\load_recon.py --file path\to\todays_statement.csv
```

Exit code 2 = mismatches detected → investigate immediately.

---

## Architecture

```
Payment request → Validation → Serial allocation → Positive Pay (same tx)
                                                         ↓
                 Audit log ← Status update ← Signature ← Render PDF
```

| Module | Purpose | Spec section |
|---|---|---|
| `src/validation.py` | Routing mod-10, account, amount, payee | §4.3 |
| `src/micr.py` | 65-position E-13B code-line builder | §4.1–4.2 |
| `src/renderer.py` | ReportLab 1:1 PDF, face + reverse | §5, §6, §7 |
| `src/sequence.py` | Gapless serial ledger (SQLite) | §10.2 |
| `src/amounts.py` | Cents → courtesy + legal amount | §6 |
| `src/positive_pay.py` | Positive Pay issue file (same tx as serial) | §10.1, §11 |
| `src/reconciliation.py` | BAI2/CSV ingest, mismatch alerts | §10.2 |
| `src/signature_vault.py` | AES-256-GCM encrypted signature | §11 |
| `src/audit.py` | Append-only event log (UPDATE/DELETE blocked) | §11 |
| `src/print_pipeline.py` | Full orchestrator | §10.1 |

---

## E-13B Font

The MICR code line requires the **E-13B** vector font for correct pitch (8 chars/inch). Download **GnuMICR** (free, open source) from https://sandeen.net/GnuMICR and place `GnuMICR.otf` in the `fonts/` directory.

**Do not print live stock without this font** — the fallback Courier font does not have the correct magnetic character shapes.

---

## Security Controls (buildspec.md §11)

| Control | Implementation |
|---|---|
| Signature encrypted at rest | AES-256-GCM vault, `vault/signature.svlt` |
| Dual-control / hard-cap | Configurable `signature_auto_threshold_cents` |
| Sequential stock accountability | Gapless serial ledger; VOID records for gaps |
| Positive Pay by default | No check record is `printed` without an export ID |
| Immutable audit log | SQLite triggers block UPDATE/DELETE on `audit_events` |
| Production lock | `PRODUCTION_LOCK=LIVE` required to send to printer |

---

## Test Evidence for the Bank (buildspec.md §12)

| Test | How to run | Pass criterion |
|---|---|---|
| Routing check digit | `pytest tests/test_validation.py -v` | All routing tests pass |
| Code-line structure | `pytest tests/test_micr.py -v` | Length=65, transit symbols in place |
| PDF geometry | `pytest tests/test_renderer.py -v` | 8.5×3.5 in, 2 pages |
| Image survivability | Print one voided check; deposit by mobile capture | All fields legible |
| **Bank test deck** | Print 20 voided samples; submit to bank's MICR lab | **Written bank approval** |
| Signal level | Bank lab or MICR verifier | 50%–200% of nominal |

---

## Build Sequence (buildspec.md §13)

| Phase | Status |
|---|---|
| 1. Buy X9.100 standards + request bank spec form | ⬜ Your action |
| 2. Procure hardware (§9 BOM) | ⬜ Your action |
| 3. Software build | ✅ Complete (this repo) |
| 4. Internal QA: run pytest, print on plain paper, use gauge | ⬜ Your action |
| 5. Send 20-sample test deck; iterate on bank feedback | ⬜ Your action |
| 6. Enroll in Positive Pay + wire export | ⬜ Your action (scripts ready) |
| 7. Reconciliation ingest | ⬜ Your action (scripts ready) |
| 8. Go live on low-value run | ⬜ Your action |

---

*This software is built to the specification in buildspec.md. The ANSI X9.100 standards are the controlling technical text. Nothing here is legal advice. Have your deposit agreement reviewed before printing live stock.*
