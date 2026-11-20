"""배포용 Zip 생성: downloads/HOMEONQ_Integrated_App.zip

    python scripts/make_zip.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]  # /workspace
OUT = WORKSPACE / "downloads" / "HOMEONQ_Integrated_App.zip"
TOP = "HOMEONQ_Integrated_App"

EXCLUDE_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache",
                ".expo", "dist", "web-build", ".idea", ".vscode"}
EXCLUDE_SUFFIX = {".pyc", ".db", ".db-wal", ".db-shm", ".zip", ".log"}
EXCLUDE_NAMES = {".env", ".DS_Store"}


def iter_files(base: Path):
    for path in sorted(base.rglob("*")):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix in EXCLUDE_SUFFIX or path.name in EXCLUDE_NAMES:
            continue
        yield path


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_files(ROOT))
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            arcname = f"{TOP}/{path.relative_to(ROOT).as_posix()}"
            zf.write(path, arcname)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"생성: {OUT} ({len(files)}개 파일, {size_mb:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
