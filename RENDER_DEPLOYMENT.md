# Free Deployment on Render.com

This guide provides step-by-step instructions to deploy the ANSI X9 Check Engine & Remittance Studio for **free** on [Render.com](https://render.com).

---

## Why Render Free Tier?

- **100% Free**: Free tier Web Service with 512MB RAM.
- **Automated SSL/TLS**: Free custom and `.onrender.com` HTTPS subdomains.
- **Direct GitHub Sync**: Automatically rebuilds and redeploys when you push new commits.
- **Native Health Checking**: Monitors `/api/health` to ensure zero-downtime deploys.
- **Pre-configured Blueprint**: `render.yaml` configures everything in one click.

---

## Deployment Instructions

### Step 1: Push Repository to GitHub

Ensure your latest code and `render.yaml` are pushed to GitHub:

```bash
git add .
git commit -m "feat: add render.yaml blueprint for free web service deployment"
git branch -M main
git push -u origin main
```

*(If you haven't added your GitHub remote yet: `git remote add origin https://github.com/<your-username>/chedck.git`)*

---

### Step 2: Deploy on Render

#### Option A: One-Click Blueprint (Recommended)

1. Log into your [Render Dashboard](https://dashboard.render.com/) (Sign in with GitHub).
2. Click **Blueprints** on the top menu.
3. Click **New Blueprint Instance**.
4. Select your `chedck` repository and grant access.
5. Render reads `render.yaml` automatically and configures:
   - Service name: `chedck`
   - Runtime: `Docker` (using our multi-stage `Dockerfile`)
   - Plan: **Free**
   - Healthcheck: `/api/health`
6. Click **Apply**.

---

#### Option B: Manual Web Service Setup

1. In the Render Dashboard, click **New +** ➔ **Web Service**.
2. Select **Build and deploy from a Git repository** ➔ Click **Next**.
3. Choose your `chedck` repository.
4. Fill in the following settings:
   - **Name**: `chedck`
   - **Region**: `Oregon (US West)` or `Frankfurt (EU)`
   - **Branch**: `main`
   - **Runtime**: `Docker`
   - **Instance Type**: **Free**
5. Under **Advanced**:
   - **Health Check Path**: `/api/health`
   - **Docker Build Context Directory**: `.`
   - **Dockerfile Path**: `./Dockerfile`
6. Click **Create Web Service**.

---

### Step 3: Access Your Live Application

Render will pull your repository, build the multi-stage Docker image (building the Vite React UI and packaging the Python FastAPI backend), and launch the service.

Once the build is complete (typically 2–3 minutes):
- Your service URL will be displayed at the top: `https://chedck.onrender.com` (or your chosen service name).
- Open the URL in your browser to access the live Check Printing & Remittance Studio UI.
- API endpoints are active at `https://<your-service>.onrender.com/api/...`

---

## Environment Variables on Render

The default settings in `render.yaml` provide:

| Variable | Value | Purpose |
|---|---|---|
| `PRODUCTION_LOCK` | `TEST` | Protects against accidental live check printing |
| `PYTHONUNBUFFERED` | `1` | Real-time log streaming in Render web console |
| `PORT` | `8000` | Port for the unified API and UI server |

To change any variable (for example, switching `PRODUCTION_LOCK` to `LIVE` after bank sample approval), go to your service in the Render Dashboard ➔ **Environment** tab ➔ Edit and save.
