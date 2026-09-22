"""
meta_clean.py — Metadata reader and cleaner.

Reads ALL metadata from image and document files, prints a structured
report highlighting sensitive fields, then optionally strips every metadata
field and saves a clean output file.

Supported formats:
  Images   : JPEG, PNG, TIFF, WEBP, BMP, GIF, HEIC/HEIF
  Documents: PDF, DOCX, XLSX, PPTX

Usage:
    # Read-only report (no changes)
    python scripts/meta_clean.py photo.jpg

    # Read then clean (saves photo.clean.jpg)
    python scripts/meta_clean.py photo.jpg --clean

    # Clean in-place (OVERWRITES original — cannot be undone)
    python scripts/meta_clean.py photo.jpg --clean --in-place

    # Process an entire directory recursively
    python scripts/meta_clean.py ./docs/ --clean --recursive

    # JSON output (machine-readable)
    python scripts/meta_clean.py photo.jpg --json

Requirements:
    pip install Pillow pikepdf python-docx openpyxl python-pptx
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional dependency guards — each section degrades gracefully if missing
# ---------------------------------------------------------------------------

try:
    from PIL import Image, ExifTags
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import pikepdf
    _HAS_PIKEPDF = True
except ImportError:
    _HAS_PIKEPDF = False

try:
    import docx as _docx
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False

try:
    import openpyxl as _openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

try:
    from pptx import Presentation as _Pptx
    _HAS_PPTX = True
except ImportError:
    _HAS_PPTX = False


# ---------------------------------------------------------------------------
# ANSI colour helpers (auto-disabled when stdout is not a TTY)
# ---------------------------------------------------------------------------

class _C:
    RESET  = "\033[0m";  BOLD   = "\033[1m"
    RED    = "\033[91m"; GREEN  = "\033[92m"
    YELLOW = "\033[93m"; CYAN   = "\033[96m"
    DIM    = "\033[2m"


def clr(text: Any, *codes: str) -> str:
    if not sys.stdout.isatty():
        return str(text)
    return "".join(codes) + str(text) + _C.RESET


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class MetaResult:
    def __init__(self, path: Path):
        self.path = path
        self.fields: dict[str, Any] = {}
        self.cleaned = False
        self.out_path: Path | None = None
        self.error: str | None = None

    def add(self, key: str, value: Any) -> None:
        if value not in (None, "", b"", [], {}, "Unknown"):
            self.fields[key] = value

    def to_dict(self) -> dict:
        return {
            "file":    str(self.path),
            "fields":  {k: str(v) for k, v in self.fields.items()},
            "cleaned": self.cleaned,
            "output":  str(self.out_path) if self.out_path else None,
            "error":   self.error,
        }


# ---------------------------------------------------------------------------
# IMAGE: JPEG / PNG / TIFF / WEBP / BMP / GIF / HEIC
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif",
               ".webp", ".bmp", ".gif", ".heic", ".heif"}


def _gps_decimal(coord, ref: str) -> str:
    try:
        d = float(coord[0]) + float(coord[1]) / 60 + float(coord[2]) / 3600
        return f"{(-d if ref in ('S', 'W') else d):.6f}"
    except Exception:
        return str(coord)


def read_image_meta(path: Path) -> MetaResult:
    r = MetaResult(path)
    if not _HAS_PIL:
        r.error = "Pillow not installed — run: pip install Pillow"
        return r
    try:
        img = Image.open(path)
    except Exception as e:
        r.error = f"Cannot open: {e}"
        return r

    r.add("Format", img.format)
    r.add("Mode",   img.mode)
    r.add("Size",   f"{img.width} x {img.height} px")

    exif = img._getexif() if hasattr(img, "_getexif") else None
    if exif:
        gps = None
        for tag_id, val in exif.items():
            name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
            if name == "GPSInfo":
                gps = val
                continue
            if isinstance(val, bytes):
                try:
                    val = val.decode("utf-8", errors="replace").strip("\x00")
                except Exception:
                    val = repr(val)
            r.add(f"EXIF:{name}", val)

        if gps:
            if gps.get(2):
                r.add("GPS:Latitude",  _gps_decimal(gps[2], gps.get(1, "")))
            if gps.get(4):
                r.add("GPS:Longitude", _gps_decimal(gps[4], gps.get(3, "")))
            if gps.get(6):
                r.add("GPS:Altitude",  f"{float(gps[6]):.1f} m")
            for k, v in gps.items():
                n = ExifTags.GPSTAGS.get(k, f"GPS_{k}")
                if n not in ("GPSLatitude", "GPSLongitude", "GPSAltitude",
                             "GPSLatitudeRef", "GPSLongitudeRef"):
                    r.add(f"GPS:{n}", str(v))

    if img.format == "PNG" and hasattr(img, "info"):
        for k, v in img.info.items():
            if k != "dpi":
                r.add(f"PNG:{k}", str(v))
    return r


def clean_image(path: Path, out_path: Path) -> MetaResult:
    r = MetaResult(path)
    if not _HAS_PIL:
        r.error = "Pillow not installed"
        return r
    try:
        img = Image.open(path)
        fmt = img.format or path.suffix.lstrip(".").upper()
        if fmt in ("JPEG", "JPG") and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        kw: dict[str, Any] = {}
        if fmt in ("JPEG", "JPG"):
            kw = {"quality": 95, "optimize": True}
        elif fmt == "PNG":
            kw = {"optimize": True}
        img.save(out_path, format=fmt, **kw)
        r.cleaned = True
        r.out_path = out_path
    except Exception as e:
        r.error = str(e)
    return r


# ---------------------------------------------------------------------------
# PDF: pikepdf
# ---------------------------------------------------------------------------

_PDF_EXTS = {".pdf"}
_PDF_KEYS = ["/Title", "/Author", "/Subject", "/Keywords", "/Creator",
             "/Producer", "/CreationDate", "/ModDate", "/Trapped"]


def read_pdf_meta(path: Path) -> MetaResult:
    r = MetaResult(path)
    if not _HAS_PIKEPDF:
        r.error = "pikepdf not installed — run: pip install pikepdf"
        return r
    try:
        with pikepdf.open(path) as pdf:
            for k in _PDF_KEYS:
                v = pdf.docinfo.get(k)
                if v:
                    r.add(f"DocInfo:{k.lstrip('/')}", str(v))
            try:
                with pdf.open_metadata() as meta:
                    for k, v in meta.items():
                        r.add(f"XMP:{k}", str(v))
            except Exception:
                pass
            r.add("Pages",     len(pdf.pages))
            r.add("Encrypted", pdf.is_encrypted)
    except Exception as e:
        r.error = str(e)
    return r


def clean_pdf(path: Path, out_path: Path) -> MetaResult:
    r = MetaResult(path)
    if not _HAS_PIKEPDF:
        r.error = "pikepdf not installed"
        return r
    try:
        with pikepdf.open(path) as pdf:
            pdf.docinfo.clear()
            try:
                with pdf.open_metadata() as meta:
                    meta.clear()
            except Exception:
                pass
            pdf.save(out_path, linearize=True)
        r.cleaned = True
        r.out_path = out_path
    except Exception as e:
        r.error = str(e)
    return r


# ---------------------------------------------------------------------------
# Office Open XML: DOCX / XLSX / PPTX
# ---------------------------------------------------------------------------

_OFFICE_EXTS = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"}
_CORE_PROP_NAMES = [
    "author", "category", "comments", "content_status", "created",
    "description", "identifier", "keywords", "language", "last_modified_by",
    "last_printed", "modified", "revision", "subject", "title", "version",
]


def _read_core_props(core) -> dict:
    out = {}
    for p in _CORE_PROP_NAMES:
        v = getattr(core, p, None)
        if v:
            out[f"CoreProp:{p}"] = str(v)
    return out


def _wipe_core_props(core) -> None:
    date_props = {"created", "modified", "last_printed"}
    for p in _CORE_PROP_NAMES:
        try:
            setattr(core, p, None if p in date_props else "")
        except Exception:
            pass


def read_office_meta(path: Path) -> MetaResult:
    r = MetaResult(path)
    ext = path.suffix.lower()
    try:
        if ext in (".docx", ".docm"):
            if not _HAS_DOCX:
                r.error = "python-docx not installed — run: pip install python-docx"
                return r
            r.fields.update(_read_core_props(_docx.Document(str(path)).core_properties))
        elif ext in (".xlsx", ".xlsm"):
            if not _HAS_OPENPYXL:
                r.error = "openpyxl not installed — run: pip install openpyxl"
                return r
            wb = _openpyxl.load_workbook(str(path), read_only=True)
            r.fields.update(_read_core_props(wb.properties))
            r.add("Sheets", ", ".join(wb.sheetnames))
            wb.close()
        elif ext in (".pptx", ".pptm"):
            if not _HAS_PPTX:
                r.error = "python-pptx not installed — run: pip install python-pptx"
                return r
            r.fields.update(_read_core_props(_Pptx(str(path)).core_properties))
    except Exception as e:
        r.error = str(e)
    return r


def clean_office(path: Path, out_path: Path) -> MetaResult:
    r = MetaResult(path)
    ext = path.suffix.lower()
    try:
        shutil.copy2(path, out_path)
        if ext in (".docx", ".docm"):
            if not _HAS_DOCX:
                r.error = "python-docx not installed"
                return r
            doc = _docx.Document(str(out_path))
            _wipe_core_props(doc.core_properties)
            doc.save(str(out_path))
        elif ext in (".xlsx", ".xlsm"):
            if not _HAS_OPENPYXL:
                r.error = "openpyxl not installed"
                return r
            wb = _openpyxl.load_workbook(str(out_path))
            _wipe_core_props(wb.properties)
            wb.save(str(out_path))
            wb.close()
        elif ext in (".pptx", ".pptm"):
            if not _HAS_PPTX:
                r.error = "python-pptx not installed"
                return r
            prs = _Pptx(str(out_path))
            _wipe_core_props(prs.core_properties)
            prs.save(str(out_path))
        r.cleaned = True
        r.out_path = out_path
    except Exception as e:
        r.error = str(e)
    return r


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_ALL_EXTS = _IMAGE_EXTS | _PDF_EXTS | _OFFICE_EXTS

_SENSITIVE_RE = re.compile(
    r"gps|latitude|longitude|altitude|author|creator|producer|"
    r"last.modified|created.by|owner|operator|software|device|"
    r"make|model|serial|location|city|country|artist",
    re.IGNORECASE,
)


def _is_sensitive(key: str) -> bool:
    return bool(_SENSITIVE_RE.search(key))


def get_out_path(path: Path, in_place: bool) -> Path:
    return path if in_place else path.parent / f"{path.stem}.clean{path.suffix}"


def read_meta(path: Path) -> MetaResult:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:  return read_image_meta(path)
    if ext in _PDF_EXTS:    return read_pdf_meta(path)
    if ext in _OFFICE_EXTS: return read_office_meta(path)
    r = MetaResult(path)
    r.error = f"Unsupported file type: {ext}"
    return r


def clean_meta(path: Path, out_path: Path) -> MetaResult:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:  return clean_image(path, out_path)
    if ext in _PDF_EXTS:    return clean_pdf(path, out_path)
    if ext in _OFFICE_EXTS: return clean_office(path, out_path)
    r = MetaResult(path)
    r.error = f"Unsupported file type: {ext}"
    return r


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_report(result: MetaResult) -> None:
    kb = result.path.stat().st_size / 1024 if result.path.exists() else 0
    print()
    print(clr(f"  +-- {result.path.name} ", _C.BOLD, _C.CYAN) +
          clr(f"({kb:.1f} KB)", _C.DIM))

    if result.error:
        print(clr(f"  |   ERROR: {result.error}", _C.RED))
    elif not result.fields:
        print(clr("  |   No metadata found.", _C.DIM))
    else:
        sensitive_count = 0
        for k, v in result.fields.items():
            s = _is_sensitive(k)
            if s:
                sensitive_count += 1
            k_col = clr(f"{k:<44}", _C.YELLOW if s else _C.DIM)
            v_col = clr(str(v)[:100], _C.RED if s else "")
            flag  = clr("  [SENSITIVE]", _C.RED) if s else ""
            print(f"  |   {k_col} {v_col}{flag}")
        if sensitive_count:
            print()
            print(clr(f"  |   *** {sensitive_count} sensitive field(s) detected ***",
                      _C.RED, _C.BOLD))

    if result.cleaned:
        print(clr(f"  |   CLEAN -> {result.out_path}", _C.GREEN, _C.BOLD))

    print(clr("  +" + "-" * 60, _C.DIM))


def print_summary(results: list[MetaResult]) -> None:
    total     = len(results)
    errors    = sum(1 for r in results if r.error)
    cleaned   = sum(1 for r in results if r.cleaned)
    sensitive = sum(1 for r in results if any(_is_sensitive(k) for k in r.fields))
    print()
    print(clr("  === SUMMARY ===", _C.BOLD, _C.CYAN))
    print(f"  Files     : {total}")
    print(f"  Errors    : " + clr(str(errors),    _C.RED   if errors    else _C.GREEN))
    print(f"  Sensitive : " + clr(str(sensitive), _C.RED   if sensitive else _C.GREEN))
    print(f"  Cleaned   : " + clr(str(cleaned),   _C.GREEN if cleaned   else _C.DIM))
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect(paths: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            if p.suffix.lower() in _ALL_EXTS:
                files.append(p)
        elif p.is_dir():
            pattern = "**/*" if recursive else "*"
            for f in p.glob(pattern):
                if f.is_file() and f.suffix.lower() in _ALL_EXTS:
                    files.append(f)
        else:
            print(clr(f"  Not found: {p}", _C.RED), file=sys.stderr)
    return sorted(set(files))


def main() -> int:
    pa = argparse.ArgumentParser(
        description="Metadata reader and cleaner for images and documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    pa.add_argument("paths", nargs="+", metavar="FILE_OR_DIR",
                    help="File(s) or directory to process")
    pa.add_argument("--clean", action="store_true",
                    help="Strip all metadata and save a clean copy")
    pa.add_argument("--in-place", action="store_true",
                    help="Overwrite original file (use with --clean; DESTRUCTIVE)")
    pa.add_argument("--recursive", "-r", action="store_true",
                    help="Recurse into directories")
    pa.add_argument("--json", action="store_true",
                    help="Output results as JSON (machine-readable)")
    args = pa.parse_args()

    if args.in_place and not args.clean:
        print(clr("ERROR: --in-place requires --clean", _C.RED), file=sys.stderr)
        return 1

    if args.in_place:
        print(clr(
            "\n  WARNING: --in-place will OVERWRITE original files.\n"
            "  This cannot be undone. Ctrl-C now to abort.\n",
            _C.RED, _C.BOLD,
        ))

    files = _collect([Path(p) for p in args.paths], args.recursive)
    if not files:
        print(clr("No supported files found.", _C.YELLOW))
        return 0

    results: list[MetaResult] = []
    for path in files:
        r = read_meta(path)
        if args.clean and not r.error:
            cr = clean_meta(path, get_out_path(path, args.in_place))
            r.cleaned  = cr.cleaned
            r.out_path = cr.out_path
            if cr.error:
                r.error = cr.error
        results.append(r)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
    else:
        print(clr("\n  META READER AND CLEANER", _C.BOLD, _C.CYAN))
        print(clr(
            f"  {len(files)} file(s) — "
            "supports: jpg png tiff webp gif bmp heic pdf docx xlsx pptx",
            _C.DIM,
        ))
        for r in results:
            print_report(r)
        print_summary(results)

    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
