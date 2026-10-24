#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Package the oa-pdf-download skill into a standard ZIP bundle
according to the official Tencent WorkBuddy Skill Specification (open.workbuddy.cn/docs/skill).
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
ZIP_FLAT = ROOT / "oa-pdf-download.zip"
ZIP_NESTED = ROOT / "oa-pdf-download-nested.zip"

INCLUDE_FILES = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "manifest.json",
    "icon.png",
    "examples/sample_papers.csv",
    "references/publisher-routes.md",
    "references/anti-bot-and-network.md",
    "scripts/fetch_oa_pdfs.py",
]


def build_package():
    print("[*] Packaging Skill for Tencent WorkBuddy (open.workbuddy.cn/docs/skill)...")
    
    # 1. Standard Flat Package (SKILL.md at zip root)
    count = 0
    with zipfile.ZipFile(ZIP_FLAT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE_FILES:
            src = ROOT / rel
            if src.exists():
                zf.write(src, arcname=rel)
                print(f"  [+] Added: {rel}")
                count += 1
            else:
                print(f"  [-] Missing: {rel}")

    size_kb = ZIP_FLAT.stat().st_size / 1024
    print(f"\n[OK] Standard Package built: {ZIP_FLAT.name} ({size_kb:.1f} KB, {count} files)")
    print(f"     Path: {ZIP_FLAT.resolve()}")

    # 2. Nested Package with outer folder (oa-pdf-download/SKILL.md)
    with zipfile.ZipFile(ZIP_NESTED, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE_FILES:
            src = ROOT / rel
            if src.exists():
                zf.write(src, arcname=f"oa-pdf-download/{rel}")

    print(f"[OK] Nested Package built: {ZIP_NESTED.name} (with 'oa-pdf-download/' root folder)")
    print(f"     Path: {ZIP_NESTED.resolve()}")


if __name__ == "__main__":
    build_package()
