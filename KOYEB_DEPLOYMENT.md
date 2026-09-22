# Free Deployment on Koyeb

This guide describes how to deploy the ANSI X9 Check Engine & Remittance Studio for **free** on [Koyeb](https://www.koyeb.com) with automatic HTTPS and global edge routing.

---

## Why Koyeb Free Tier?

- **100% Free**: 1 Free Eco / Nano Web Service with 512MB RAM and 0.1 vCPU.
- **Built-in Global Edge**: Fast response times with automated TLS/SSL certificate (`https://<app-name>-<user>.koyeb.app`).
- **Direct GitHub Integration**: Continuous deployment on every git push.
- **Pre-configured App Spec**: `koyeb.yaml` and multi-stage `Dockerfile` are already included in this repository.

---

## Deployment Steps

### Step 1: Commit and Push to GitHub

1. Stage and commit your files:
   ```bash
   git add .
   git commit -m "feat: complete containerized check printing system for Koyeb deployment"
   ```

2. Create a new repository on GitHub (named e.g. `chedck`) and push your code:
   ```bash
   git branch -M main
   git remote add origin https://github.com/<your-username>/chedck.git
   git push -u origin main
   ```

---

### Step 2: Deploy on Koyeb

1. Go to [app.koyeb.com](https://app.koyeb.com) and log in (or sign up with GitHub).
2. Click **Create Service**.
3. Under **Deployment Method**, select **GitHub**.
4. Choose your repository: `<your-username>/chedck`.
5. Under **Builder**, select **Dockerfile** (Koyeb will automatically use the root `Dockerfile`).
6. Under **Instance Type**, select **Nano** (`Free`).
7. Under **Regions**, select **Washington, D.C. (was)** or **Frankfurt (fra)**.
8. Under **Exposed Ports**, ensure:
   - **Port**: `8000`
   - **Protocol**: `HTTP`
   - **Path**: `/`
9. Under **Health Checks**:
   - **Protocol**: `HTTP`
   - **Path**: `/api/health`
10. Click **Deploy**.

---

### Step 3: Access Your Live Application

Koyeb will build the multi-stage Docker image, start the service, and verify the `/api/health` check.

Once the status turns to **Healthy**:
- Open the public URL provided by Koyeb: `https://<service-name>-<organization>.koyeb.app`
- Both the React UI and API endpoints are live and secured with HTTPS.

---

## Environment Variables on Koyeb

If needed, you can set the following in the Koyeb service settings under **Environment variables**:

| Variable | Value | Purpose |
|---|---|---|
| `PRODUCTION_LOCK` | `TEST` (default) or `LIVE` | Safeguard against accidental physical printing |
| `PYTHONUNBUFFERED` | `1` | Real-time console logging in Koyeb web dashboard |
| `PORT` | `8000` | Koyeb dynamically assigns this port |
