"""
start_ui.py — Launch script for Check Engine UI & API Server.

Starts:
1. FastAPI API server at http://127.0.0.1:8000
2. Vite Dev Server at http://127.0.0.1:5173
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
UI_DIR = ROOT / "ui"

def main():
    print("==================================================")
    print("  ANSI X9 Check Engine & Remittance Studio UI     ")
    print("==================================================")
    print("Starting API Backend (FastAPI on port 8000)...")

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1", "--port", "8000", "--app-dir", "src"],
        cwd=str(ROOT),
    )

    time.sleep(1.5)

    print("Starting Vite Dev Server (React on port 5173)...")
    vite_proc = subprocess.Popen(
        ["npm.cmd" if sys.platform == "win32" else "npm", "run", "dev"],
        cwd=str(UI_DIR),
    )

    print("\n[OK] Studio running at: http://127.0.0.1:5173\n")
    print("Press Ctrl+C to stop both servers.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down servers...")
        api_proc.terminate()
        vite_proc.terminate()
        print("Done.")

if __name__ == "__main__":
    main()
