# Deployment Guide — chedck Check Printing System

This guide outlines how to deploy the ANSI X9 Check Engine & Remittance Studio in production using Docker and Docker Compose.

---

## Architecture Overview

The production container combines:
1. **Frontend**: React + Vite UI compiled to high-performance static assets.
2. **Backend**: FastAPI API running with Uvicorn.
3. **Engine**: ReportLab PDF generator + MICR E-13B formatting + AES-256-GCM signature vault.
4. **Unified Access**: Both the web application and REST API run together on port `8000`.

---

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/) (v2.0+)

---

## Quick Start Deployment

### 1. Build and Launch the Container

From the repository root directory, run:

```bash
docker compose up -d --build
```

This will:
- Compile the Vite frontend inside the `node:22-alpine` builder stage.
- Package the FastAPI application into a slim `python:3.12` runtime container.
- Start the server on `http://localhost:8000`.

### 2. Verify Deployment Health

Check container status and health:

```bash
docker compose ps
```

Verify the API healthcheck endpoint:

```bash
curl http://localhost:8000/api/health
```

Expected output:
```json
{"status":"ok","timestamp":"2026-09-21T18:00:00.000000+00:00"}
```

Access the Studio UI by opening `http://localhost:8000` in your web browser.

---

## Persistent Storage & Volumes

All mutable data, security configurations, and audit logs are mapped to host volumes to ensure zero data loss during container upgrades:

| Host Path | Container Path | Purpose |
|---|---|---|
| `./db` | `/app/db` | SQLite databases (`checks.db`, `audit.db`) |
| `./output` | `/app/output` | Generated check PDFs and Positive Pay files |
| `./config` | `/app/config` | Bank, account, and security policies |
| `./fonts` | `/app/fonts` | TrueType E-13B MICR fonts (`GnuMICR.ttf`) |
| `./vault` | `/app/vault` | Encrypted signature vault (`signature.svlt`) |

---

## Production Security & Live Printing

By default, the system launches with `PRODUCTION_LOCK=TEST`. Checks are rendered in test mode and cannot be dispatched to physical MICR printers.

### Enabling Live Printing

Once your bank MICR sample deck has received written approval:

1. Update your `.env` file or export the environment variable:
   ```bash
   PRODUCTION_LOCK=LIVE
   ```
2. Or set `"production_lock": "LIVE"` in `config/security_config.json`.
3. Restart the container:
   ```bash
   docker compose up -d
   ```

---

## Operational Commands

### View Live Logs
```bash
docker compose logs -f chedck
```

### Export Positive Pay File Inside Container
```bash
docker compose exec chedck python scripts/export_positive_pay.py --all-pending
```

### Run Reconciliation Ingest
```bash
docker compose exec chedck python scripts/load_recon.py --file /app/output/bank_statement.csv
```

### Stop Service
```bash
docker compose down
```
