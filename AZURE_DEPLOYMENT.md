# Azure Deployment Guide — chedck Check Engine & Remittance Studio

This guide documents the live deployment of the ANSI X9 Check Engine & Remittance Studio on **Azure App Service (Linux / Python 3.12)**.

---

## Live Production Deployment

- **Live URL**: [https://chedck-studio.azurewebsites.net](https://chedck-studio.azurewebsites.net)
- **Health Check**: [https://chedck-studio.azurewebsites.net/api/health](https://chedck-studio.azurewebsites.net/api/health)
- **Resource Group**: `rg-omnileadfeeder-production`
- **Region**: Central US
- **Runtime**: Python 3.12 (`PYTHON|3.12`) with Uvicorn ASGI server

---

## Architecture Overview

```
                      Internet (HTTPS)
                             │
                             ▼
            ┌──────────────────────────────────┐
            │  chedck-studio.azurewebsites.net │
            │      Azure Linux App Service     │
            │         Port 8000 / Uvicorn      │
            └─────────────────┬────────────────┘
                              │
     ┌────────────────────────┴────────────────────────┐
     ▼                                                 ▼
┌─────────────────────────┐               ┌─────────────────────────┐
│     React + Vite UI     │               │     FastAPI Backend     │
│  (Static Single Page)   │               │   (Engine, MICR, PDF)   │
│  Mounted from /ui/dist  │               │   Mounted at /api/*     │
└─────────────────────────┘               └─────────────────────────┘
```

The unified single-port architecture provides:
1. **Frontend**: React + Vite UI compiled to static assets (`ui/dist/`) and served directly by FastAPI.
2. **Backend**: FastAPI with Uvicorn running on port `8000`.
3. **Check & Voucher Engine**: ReportLab PDF generator + MICR E-13B TrueType font formatting (`fonts/GnuMICR.ttf`) + pypdfium2 PNG preview rendering.
4. **Configuration & Ledger**: Managed under `/config` and `/db`.

---

## Automated Packaging & Deployment Workflow

### 1. Build Frontend & Create Deployment Package
The repository includes an automated packaging tool [`scripts/package_azure.py`](file:///c:/Users/ben/chedck/scripts/package_azure.py) that builds a clean production zip bundle including:
- Application source (`src/`)
- Bank, account, and security configuration (`config/`)
- TrueType E-13B fonts (`fonts/`)
- Compiled Vite frontend bundle (`ui/dist/`)
- Linux executable startup script (`startup.sh`)
- `requirements.txt`

Run:
```powershell
# Build frontend bundle
cd ui; npm run build; cd ..

# Generate clean deploy.zip
python scripts/package_azure.py
```

### 2. Deploy to Azure App Service
Deploy `deploy.zip` directly to the Azure Web App:

```powershell
az webapp deploy `
  --name chedck-studio `
  --resource-group rg-omnileadfeeder-production `
  --src-path deploy.zip `
  --type zip
```

---

## App Service Configuration Reference

| Setting | Value | Description |
|---|---|---|
| `appCommandLine` | `startup.sh` | Activates Oryx virtualenv and launches Uvicorn on `$PORT` |
| `WEBSITES_PORT` | `8000` | Instructs Azure App Service routing to bind to port 8000 |
| `PYTHONPATH` | `/home/site/wwwroot/src` | Ensures `src/` modules are importable globally |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Enables Oryx to install dependencies from `requirements.txt` |
| `PRODUCTION_LOCK` | `TEST` | Default safety lock (`TEST` vs `LIVE`) |

---

## Operational Commands

### Live Health Check
```powershell
curl.exe -i https://chedck-studio.azurewebsites.net/api/health
```

### Next Serial Number Check
```powershell
curl.exe -i https://chedck-studio.azurewebsites.net/api/checks/next-serial
```

### Stream Live Logs
```powershell
az webapp log tail --name chedck-studio --resource-group rg-omnileadfeeder-production
```

### Restart Web App
```powershell
az webapp restart --name chedck-studio --resource-group rg-omnileadfeeder-production
```
