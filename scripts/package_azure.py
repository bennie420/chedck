"""
package_azure.py — Packages the application for Azure App Service deployment.
"""

import os
import zipfile
from pathlib import Path

def create_azure_package():
    root_dir = Path(__file__).resolve().parent.parent
    zip_path = root_dir / "deploy.zip"

    if zip_path.exists():
        zip_path.unlink()

    print(f"Creating Azure deployment zip: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. requirements.txt
        zf.write(root_dir / "requirements.txt", "requirements.txt")
        print("Added requirements.txt")

        # 2. startup.sh
        startup_sh = root_dir / "startup.sh"
        if startup_sh.exists():
            # Force Linux newline endings (LF)
            content = startup_sh.read_bytes().replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo("startup.sh")
            info.external_attr = 0o755 << 16  # rwxr-xr-x
            zf.writestr(info, content)
            print("Added startup.sh with executable permissions (LF)")

        # 3. src/
        for p in (root_dir / "src").rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                arcname = p.relative_to(root_dir)
                zf.write(p, str(arcname).replace("\\", "/"))
        print("Added src/ files")

        # 4. config/
        for p in (root_dir / "config").rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                arcname = p.relative_to(root_dir)
                zf.write(p, str(arcname).replace("\\", "/"))
        print("Added config/ files")

        # 5. fonts/
        for p in (root_dir / "fonts").rglob("*"):
            if p.is_file():
                arcname = p.relative_to(root_dir)
                zf.write(p, str(arcname).replace("\\", "/"))
        print("Added fonts/ files")

        # 6. ui/dist/
        ui_dist = root_dir / "ui" / "dist"
        if not ui_dist.exists() or not (ui_dist / "index.html").exists():
            raise RuntimeError("ui/dist does not exist! Run 'npm run build' in ui/ first.")

        for p in ui_dist.rglob("*"):
            if p.is_file():
                arcname = p.relative_to(root_dir)
                zf.write(p, str(arcname).replace("\\", "/"))
        print("Added ui/dist/ files")

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Deployment zip successfully created: {size_mb:.2f} MB")

if __name__ == "__main__":
    create_azure_package()
