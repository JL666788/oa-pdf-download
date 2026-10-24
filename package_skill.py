#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper script to package the oa-pdf-download skill into a standard ZIP bundle
for WorkBuddy (open.workbuddy.cn) and other AI Agent skill ecosystems.
"""

import os
import sys
import zipfile
from pathlib import Path

# Enable UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
OUTPUT_ZIP = ROOT / "oa-pdf-download.zip"

INCLUDE_FILES = [
    "manifest.json",
    "SKILL.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "examples/sample_papers.csv",
    "scripts/fetch_oa_pdfs.py",
]


def build_package():
    print("[*] Packaging Skill for WorkBuddy...")
    count = 0
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE_FILES:
            src = ROOT / rel
            if src.exists():
                zf.write(src, arcname=rel)
                print(f"  [+] Added: {rel}")
                count += 1
            else:
                print(f"  [-] Missing: {rel}")

    size_kb = OUTPUT_ZIP.stat().st_size / 1024
    print(f"\n[OK] Package built successfully: {OUTPUT_ZIP.name} ({size_kb:.1f} KB, {count} files)")
    print(f"Location: {OUTPUT_ZIP.resolve()}")


if __name__ == "__main__":
    build_package()
