# In-House Check Printing System — Build Specification

**Revision 1.0 · 19 September 2026 · Prepared for OmniLeadFeeder**

---

## 0. Purpose, scope, and the one non-negotiable rule

This spec defines what you need to design, build, and qualify a self-contained check-printing setup that replaces a dedicated check-printer appliance: document geometry, paper, the magnetic code line, image survivability, security features, the software pipeline, and the test evidence your bank will ask for.

Two ideas drive every requirement below. A check is a **negotiable instrument** — its legal force comes from UCC Article 3, not from how it looks. It is also a **machine-readable document** that will be scanned, truncated to an image, and cleared electronically under Check 21. What actually breaks checks in production is magnetic signal defects, code-line misplacement, and backgrounds that destroy image quality. Build for the machine and the law takes care of itself.

**The non-negotiable rule:** before you print live stock, your drawee bank must run a **pre-production test deck** (typically 20 voided, burst samples) through their MICR quality lab and sign off. Every major bank requires this on the first order and on every design change. JPMorgan Chase's published printer spec, for example, requires 20 pre-production samples on all orders and reorders, and warns that ongoing MICR quality errors can produce posting delays and penalty charges. Budget two to three weeks for this loop and do not skip it — most deposit agreements put the loss from a misencoded item on the drawer, not the bank.

Scope: checks drawn on your own account, printed on your own equipment. Printing checks for third parties, or printing on behalf of another party's account, pulls in money-transmission and bank-vendor requirements that are outside this document.

---

## 1. Normative standards and regulations

### 1.1 ANSI ASC X9 standards (the technical rulebook)

| Standard | What it governs |
|---|---|
| **X9.100-10** (2021) | Paper for MICR documents: physical strength and surface characteristics so items survive multiple passes through high-speed reader/sorters. Explicitly excludes security-feature specs. |
| **X9.100-20** (2021) | Printing MICR characters: shape, dimensions, magnetic signal level, and tolerances for the fourteen E-13B characters, plus the catalogue of print defects and allowed tolerances. |
| **X9.100-30** (2011, S2022) | Optical background measurement: reflectance, print contrast signal (PCS), document contrast ratio, paxel count, opacity. |
| **X9.100-110** (2021) | Document imaging compatibility: location and background design of essential check data fields, for business-size and personal-size checks. |
| **X9.100-111** (2025) | Physical check endorsements — the reverse-side zones. Referenced by name in Regulation CC. |
| **X9.100-160-1** (2021) | MICR formatting: vertical and horizontal format of the print band, placement and location of the code line, tolerances between characters and between fields, leading/trailing edge considerations, and restrictions on magnetic vs. nonmagnetic ink in specified areas. |
| **X9.100-160-2** (2020, R2025) | External Processing Code (EPC) field use — the single optional digit left of the routing field. |
| **X9.100-140** | Image Replacement Document (substitute check) construction, layout, data elements, and print specs. |
| **X9.100-187** | Electronic exchange of check and image data (domestic). The format your item ends up in. |
| **X9.100-170** | Check fraud deterrent icon (the padlock). |
| **TR-2 / TR-6 / TR-8** | Technical reports: *Understanding, Designing and Producing Checks*; *Guide to Quality MICR Printing and Evaluation*; *Check Security*. TR-6 is the practical QA companion to X9.100-20. |

Buy the **X9.100 Core Check Printer Package** from the ANSI webstore (X9.100-10, -20, -30, -110, -111, -160-1, -160-2; roughly $250 as a bundle versus ~$115 per standard individually). Add TR-6 and TR-8 separately. This is the single best money you will spend on the project — everything below is a summary, and the standards are the controlling text.

### 1.2 Legal and regulatory baseline

| Authority | What it requires of your check |
|---|---|
| **UCC §3-104** | To be negotiable: an unconditional order to pay a fixed amount of money, payable on demand, signed by the drawer, payable to order or bearer, with no other undertaking. This is what makes the piece of paper a check. |
| **UCC §4-401 / §3-403** | The bank may charge your account only for items *properly payable*. Unauthorized signatures and alterations shift loss — which is why signature control (§11) is a design requirement, not an afterthought. |
| **UCC §4-406** | Your duty to examine statements and report unauthorized items promptly, typically within 30 days. Drives the reconciliation feature in §10. |
| **Check 21 Act / 12 CFR 229 subpart D** | Your item will almost certainly be truncated to an image or a substitute check. The face must survive greyscale/bitonal imaging at 200 dpi — this is why background design (§5) matters more than aesthetics. |
| **Reg CC §229.35 + Appendix D** | Banks must indorse per X9.100-111 (paper), X9.100-140 (substitute checks), X9.100-187 (electronic). Practical effect: keep the reverse-side bank zones clear (§7). |
| **Reg CC §229.38(d)** | If the depositary bank's routing number is unreadable because of material on the back of the check, loss from the delayed return falls on that bank — another reason banks police the back-of-item design. |
| **Your deposit agreement** | Almost always assigns you responsibility for MICR print quality, check-stock security, and losses from your own encoding errors. Read the encoding-standards clause before you build. |
| **State law** | Some states regulate check-cashing-adjacent activity and stale-dating conventions. Nothing unusual applies to a business printing its own checks on its own account. |

---

## 2. Document geometry

| Attribute | Requirement | Notes |
|---|---|---|
| Width | **7.25 in minimum, 8.750 in maximum** | Business checks typically 8.5 in. Personal-size checks sit at the low end (~6.0 in is below the reader/sorter minimum for business processing — stay in range). |
| Height | **2.750 in minimum, 3.667 in maximum** | 3.5 in is the common business height; 2.75 in for personal-size. |
| Corner radius | Square or lightly rounded | Avoid rounded corners deeper than 1/8 in; feeders singulate on the corner. |
| Edge quality | Clean, burst or guillotine cut | Perforation stubs inside the document boundary cause jams and MICR rejects. |
| Skew tolerance | Code line parallel to the bottom edge | Skew is the single most common home-grown failure; see §4.4. |
| Leading edge | Right edge (as you look at the face) | The edge that enters the reader/sorter first. The **trailing** edge is the left edge of the face. Get this straight before reading §4 and §7. |

Design on a 1:1 grid in points or inches. Never design at a scale and rescale on output — printer driver scaling is the second most common cause of code-line position failures.

---

## 3. Substrate and consumables

| Item | Requirement | Why |
|---|---|---|
| Paper | **MICR-grade bond, 24 lb minimum** | Below 24 lb, items tear on multi-pass sorts. X9.100-10 sets strength and surface attributes. |
| Finish | Smooth, uncoated, low-gloss | Coated or glossy stock scatters the scanner's illumination and kills PCS. |
| Opacity | High; no show-through of the reverse print | Show-through into the clear band causes false character reads. |
| Brightness/colour | Light, low-saturation face; avoid dark or high-contrast backgrounds | X9.100-30/-110 govern reflectance and contrast measurement. |
| Toner/ink | **Genuine MICR toner** (magnetic iron-oxide) | Non-MICR toner is the number-one reject reason. Never use remanufactured or refilled MICR cartridges: signal level drifts out of tolerance mid-cartridge. |
| Signature ink | Not applicable if signature is printed with the same MICR toner | Printed signatures are legal but see §11 on control. |
| Storage | Locked, access-logged, sequential-numbered | Do not stock more than a one-year supply of blank stock. |

Buy blank MICR-grade stock with the security features already embedded (§8) rather than trying to print security features yourself. Pre-secured blank stock plus your own MICR printing is the sweet spot for a small operation: you get the substrate features you cannot replicate on a desktop, and you keep control of the account data.

---

## 4. The MICR code line — the part that must be exactly right

### 4.1 Band geometry

| Element | Dimension |
|---|---|
| **Clear band** | **0.625 in** high, measured from the bottom edge of the document, running the full width of the face |
| **Print band** | **0.250 in** high, centred inside the clear band |
| Border above and below the print band | **0.1875 in** each |
| Character pitch | **8 characters per inch (0.125 in per position)** |
| Position numbering | Position 1 at the **right** (leading) edge, increasing leftward, to position 65 |

Nothing but MICR characters may appear in the clear band. No signature descenders, no address text, no logo, no border rule, no perforation, no background tint or void pantograph. This is the most frequently violated rule on self-printed checks and it produces hard rejects.

### 4.2 Field positions

| Positions | Field | Rule |
|---|---|---|
| 1–12 | **Amount** | Leave blank. The bank of first deposit encodes it. |
| 13 | Separator | Blank. |
| 14–31 | **On-Us** (account number, optionally serial) | Right-justified, no zero fill. Leave unused positions blank. Some banks narrow this — e.g. Chase specifies positions 19–31 for the account field. |
| 32 | Separator | Blank. |
| 33–43 | **Routing/transit** | Nine digits bounded by transit symbols at 33 and 43. |
| 44 | **EPC** (External Processing Code) | Optional single digit. Reserved — leave blank unless the bank instructs otherwise. A "2" here identifies a qualified return item. |
| 45–65 | **Auxiliary On-Us** | Business-size checks only: the check serial number, bounded by On-Us symbols, right-justified to the bank's specified box (Chase, for example, uses 46–55 with the last serial digit in box 46). |

**Get the exact field map from your bank in writing.** The standard defines the framework; each drawee bank publishes a MICR Document Specification form (the subject of X9.100-161) that fixes the field boundaries for your account. Build your software to read that form's values from configuration, never hard-code them.

The four E-13B special symbols are Transit, Amount, On-Us, and Dash. Only the ten digits and these four symbols are valid — no alphabetic characters anywhere in the code line.

### 4.3 Routing number validation (implement this in code)

The nine-digit routing/transit number carries a mod-10 check digit. Validate every routing number before it reaches print:

```
(3 × (d1 + d4 + d7) + 7 × (d2 + d5 + d8) + 1 × (d3 + d6 + d9)) mod 10 == 0
```

Also render the **fractional routing number** in the upper-right of the face (format `prefix-suffix/FRB`, e.g. `70-2322/719`). It is a legacy human-readable cross-check and banks still expect it. Account number and fractional form both belong in the upper-right block per most bank layout guides.

### 4.4 Signal quality and print defects

X9.100-20 sets the magnetic signal level and tolerances; the practical acceptance window used across the industry is **50%–200% of nominal signal**, with most banks wanting 80%–150%. You cannot measure this with a ruler. Two options:

- **Qualify once, monitor with a gauge.** Buy a MICR position gauge (a transparent overlay with the 65 position boxes) for visual alignment checks on every stock change, and send the bank a test deck for magnetic verification. Adequate for low volume.
- **Buy a MICR verifier.** A handheld or desktop magnetic reader gives you a signal-level readout per character. Worth it above roughly 500 checks a month or if you print for multiple accounts.

Defects to design and QA against: voids and light spots inside characters, extraneous magnetic ink in the clear band, character skew, horizontal spacing drift across the line (usually a driver-scaling artifact), and signal fade across a toner cartridge's life.

---

## 5. Image and optical requirements

Your check will be scanned, usually bitonal at 200 dpi, and the image is what clears. Design for that:

- **Background:** pale, low-contrast, evenly toned. High-contrast patterns, dark tints, heavy borders, and reversed-out (white-on-dark) text drop out or fill in under bitonal thresholding.
- **Void pantographs:** genuinely useful against photocopying, but a badly tuned pantograph is a top-five reject cause because it images as noise. Use a pantograph designed and tested for imaging (any reputable MICR stock vendor's is), and keep it entirely out of the clear band.
- **Essential data fields** (date, payee, amount box, legal amount line, signature) must sit on clean background per X9.100-110, with no line art crossing them.
- **Logos** must not be enlarged into the clear band or over the amount box. Keep them in the upper-left block.
- **Drop-out colours** are not a reliable strategy under modern greyscale capture. Do not rely on an ink "disappearing".
- Target a print contrast signal comfortably above the X9.100-30 minimum. In practice: black or very dark navy text on a near-white background.

---

## 6. Face layout

| Field | Placement | Requirement |
|---|---|---|
| Drawer name and address | Upper-left | Your legal business name and the address you want on record. Keep it clear of the clear band. |
| Check serial number | Upper-right, large | Must match the Auxiliary On-Us serial in the code line, digit for digit. |
| Date | Upper-right, below serial | `MM/DD/YYYY` preferred. |
| Fractional routing number | Upper-right block | See §4.3. |
| Payee line | Left-centre, "PAY TO THE ORDER OF" | The "order of" wording is what preserves negotiability under §3-104. |
| Courtesy amount box | Right of the payee line | Boxed, right-aligned, leading `$`. Print the figure with a fill character (e.g. `**1,250.00`) to prevent prepending digits. |
| Legal (written) amount line | Below payee | Spelled amount plus fraction over 100, then fill the remaining line with a rule or asterisks. **The legal amount controls if the two disagree** (UCC §3-114). |
| Bank name and city | Left, below the legal line | The drawee bank exactly as the bank specifies. |
| Memo line | Lower-left | Optional. Never let it descend into the clear band. |
| Signature line | Lower-right | Above the clear band by at least 1/4 in. Add "TWO SIGNATURES REQUIRED OVER $X,XXX" only if your bank actually enforces it by agreement — the legend alone does not bind them. |
| Security legend | Along the top or bottom edge, outside the clear band | e.g. "Original document has a coloured background and micro-printed border — absence of these features indicates a copy." |

---

## 7. Reverse-side layout and endorsement zones

Measured from the **trailing edge** of the check (the left side of the face, which is the right side when you look at the back):

| Zone | Span from trailing edge | Reserved for |
|---|---|---|
| Payee endorsement | 0 to **1.5 in** | The payee's signature. Commonly used for this, not strictly mandated since the 1988 rulemaking. |
| **Depositary bank (BOFD) endorsement** | 1.5 in from the trailing edge to **3.0 in from the leading edge** | The bank of first deposit's nine-digit routing number and stamp. Keep it absolutely clear. |
| Subsequent endorsers | Remaining area toward the leading edge | Other collecting banks. |

Your printed reverse content — "Endorse here" guidance, a security warning, a watermark statement — must sit outside the BOFD zone and must be pale enough not to obscure a purple or black bank stamp. Under §229.38(d), material on the back that makes the BOFD routing number unreadable creates liability; banks look hard at this on self-printed stock.

---

## 8. Security features

Pick at least three from different categories. Most matter legally too: UCC ordinary-care analysis and many bank fraud-loss policies look at whether the drawer used reasonably available security features.

| Feature | Category | Get it from |
|---|---|---|
| Chemically reactive paper | Substrate | Pre-secured blank stock. Stains when solvents are used for alteration. |
| Visible/invisible fibres | Substrate | Pre-secured blank stock. |
| True watermark | Substrate | Pre-secured blank stock only — cannot be printed. |
| Void pantograph | Printed background | Pre-secured stock, imaging-tested (see §5). |
| Microprinting | Printed line art | Your printer, at 600 dpi or better: the signature line or border rendered as 0.6 pt repeated text that blurs on photocopy. |
| Toner anchorage | Print process | MICR toner fused with a proper fuser; resists tape-lift alteration. |
| Prismatic / multi-tone background | Printed background | Pre-secured stock. Defeats flatbed copying. |
| **Padlock icon (X9.100-170)** | Disclosure | Print the ANSI check fraud deterrent icon plus the security-feature legend (§6). Signals to tellers that features exist. |
| Security warning band | Disclosure | Printed. Lists the features present. |

Operational controls beat printed features for the fraud you will actually face. **Positive Pay with payee-name matching, enrolled with your bank, is worth more than every feature in this table combined.** Feed it from the same print run that produces the checks (§10).

---

## 9. Hardware bill of materials

| Item | Specification | Notes |
|---|---|---|
| Printer | Monochrome laser, 600 dpi minimum, straight-through or near-straight paper path, PCL or PostScript | Avoid inkjet entirely: no magnetic ink, and water-soluble. Avoid multifunction devices with curved paper paths. |
| MICR toner | OEM or certified-MICR aftermarket cartridge for that exact model | Never remanufactured. Track cartridge serial and page count. |
| Locking paper tray | Key-locked cassette dedicated to check stock | Prevents blank stock walking out and prevents non-check jobs printing on it. |
| Secure host | Dedicated workstation or VM, full-disk encryption, no shared logins | The signature image and account data live here. |
| MICR position gauge | Transparent 65-position overlay | Minimum viable QA. |
| MICR verifier (optional) | Magnetic signal-level reader | Recommended above ~500 checks/month. |
| Blank stock | 24 lb MICR bond, pre-secured, sequentially controlled | See §3 and §8. |
| Cross-cut shredder | P-4 or better | For spoiled and voided stock. |

Print the check and the MICR line in a **single pass**. Two-pass workflows (pre-printed shells plus variable data) reintroduce exactly the registration errors you are trying to avoid, and pre-printed shells are blank negotiable stock sitting in a drawer.

---

## 10. Software architecture

### 10.1 Pipeline

```
Payment request  →  Validation  →  Sequence allocation  →  Render (PDF/PS)
                                                              ↓
          Positive Pay file  ←  Print + verify  ←  Signature overlay (gated)
                    ↓
              Bank upload             →        Reconciliation ingest
```

Render deterministically to a fixed-geometry PDF at 1:1 with **all scaling disabled** in the driver ("Actual size", never "Fit to page"). Embed the E-13B font as an outline or draw the characters as vector glyphs so the pitch cannot drift. Generate the Positive Pay issue file in the same transaction that allocates the serial number, so a printed check that never reaches the bank's issue file is impossible.

### 10.2 Check record data model

| Field | Type | Rule |
|---|---|---|
| `serial_number` | integer, unique, gapless per account | Allocated in a transaction; never reused; gaps must be explained by a VOID record. |
| `account_id` | FK | Carries the bank's field map (§4.2) as configuration. |
| `routing_number` | string(9) | Mod-10 validated at write time (§4.3). |
| `payee_name` | string | Exactly as it goes to Positive Pay. |
| `amount_cents` | integer | Never a float. Courtesy and legal amounts both derived from this one value. |
| `issue_date` | date | |
| `status` | enum | `allocated`, `printed`, `voided`, `spoiled`, `cleared`, `stopped` |
| `print_batch_id` | FK | Links to operator, timestamp, printer, cartridge serial. |
| `signature_applied` | boolean + approver id | See §11. |
| `positive_pay_export_id` | FK | Null means the item is not yet protected. Alert on any `printed` record with a null here. |
| `cleared_amount_cents` | integer, nullable | From the bank reconciliation file; mismatch against `amount_cents` is an alteration alarm. |

Ingest your bank's reconciliation/BAI2 file daily and auto-compare cleared amount, payee, and serial against the issue record. This is your UCC §4-406 duty discharged automatically, and it is trivially scriptable in the same style as your existing crawler-to-Sheets pipelines.

---

## 11. Controls and segregation of duties

- **Signature image is not a file on disk.** Keep it encrypted at rest, released only by an approval step tied to a second identity, and never stored in the same repo as the templates. Above a threshold amount, require a wet signature.
- **Dual control over the amount.** The person who creates a payment request must not be the person who releases the print run. In a one-person shop, substitute a hard cap: anything above $X prints unsigned and gets signed by hand.
- **Sequential stock accountability.** Reconcile blank-stock count to serial numbers consumed after every run. Log and shred spoilage; record it as a VOID in the ledger.
- **Positive Pay by default.** No print run completes until the issue file is accepted by the bank. Treat a rejected upload as a production incident.
- **Immutable audit log** of every print, void, reprint, and signature release, with operator identity and timestamp.
- **Bank notification.** Tell your bank you are self-printing and get their spec form. Some deposit agreements require it and silently shift fraud loss if you do not.

---

## 12. Test and acceptance plan

| Test | Method | Pass criterion |
|---|---|---|
| Code-line position | MICR gauge overlay on 10 samples | Every character centred in its position box; line within the 0.250 in print band |
| Clear-band cleanliness | Visual + backlit inspection | Nothing but E-13B characters in the 0.625 in band, full width |
| Character quality | 10× loupe | No voids, light spots, or ragged edges |
| Skew | Gauge or straightedge | Code line parallel to the bottom edge within tolerance |
| Scale integrity | Measure printed width of a known 6.0 in rule | Within ±0.01 in; any deviation means driver scaling is on |
| Routing check digit | Unit test on the validator | Mod-10 passes; known-bad numbers rejected |
| Image survivability | Scan at 200 dpi bitonal, or deposit one voided item by mobile capture | All essential fields legible; background does not fill in |
| **Bank test deck** | 20 samples, burst, voided, sent to the bank's MICR quality group | Written approval before production |
| Signal level | Bank lab or MICR verifier | Within the bank's stated window (industry range 50%–200% of nominal) |
| Regression | Re-run the whole deck | On any change of stock, toner, printer, driver, or template |

---

## 13. Build sequence

| Phase | Work | Duration |
|---|---|---|
| 1 | Buy the X9.100 Core Check Printer Package plus TR-6; request your bank's MICR specification form | 1 week |
| 2 | Procure printer, MICR toner, locking tray, gauge, and pre-secured blank stock | 1–2 weeks |
| 3 | Build the renderer against your bank's field map; implement check-digit validation and the sequence ledger | 1–2 weeks |
| 4 | Internal QA per §12 on plain paper, then on real stock | 2 days |
| 5 | Send the 20-sample test deck; iterate on bank feedback | 2–3 weeks |
| 6 | Enrol in Positive Pay with payee matching; wire the issue-file export | 1 week |
| 7 | Build the reconciliation ingest and the exception alerts | 1 week |
| 8 | Go live on a low-value run; hold the first 30 days under manual review | ongoing |

---

## 14. Open items to confirm with your bank before you build

1. The exact On-Us and Auxiliary On-Us field boundaries for your account, in writing (their X9.100-161 spec form).
2. Whether they want the EPC position left blank.
3. Their accepted signal-level window and their test-deck submission address and contact.
4. Positive Pay file format, cut-off time, and whether payee-name matching is available on your account tier.
5. Whether your deposit agreement requires notice before self-printing, and what it says about encoding-error liability.
6. Their reconciliation file format and delivery channel.

---

*This specification summarises publicly documented standards and regulations. The ANSI X9.100 standards are the controlling technical text and must be purchased and followed; your bank's own specification form controls wherever it is stricter. Nothing here is legal advice — have your deposit agreement's encoding and endorsement clauses reviewed before you print live stock.*
