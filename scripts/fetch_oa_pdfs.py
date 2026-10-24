#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OA-PDF-Download: Batch-download legally open-access (OA) academic full-text PDFs.

Legal Open Access Only:
  - Compliant with publisher OA policies and repository open-access terms.
  - Zero paywall circumvention, no illicit cookie sharing, no Sci-Hub.
  - Transparently logs failed acquisitions and reasons (e.g., paywalled, HTML-only).

Pipeline Overview:
  - Phase A (Fast): Direct publisher endpoints (Springer, BMC, Frontiers, MDPI,
    J-Stage, Scialert) + Europe PMC + Semantic Scholar openAccessPdf probe.
  - Phase B (Paced & Adaptive): PMC (pmc.ncbi.nlm.nih.gov) with automatic
    Hashcash Proof-of-Work (PoW) interstitial solver and anti-bot escalation backoff.

Author: JL666788
License: MIT
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

# Suppress insecure request warnings if verify=False is needed for legacy certs
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)


# ==============================================================================
# UI & Formatting Helpers
# ==============================================================================

class Colors:
    """ANSI color codes for stylish terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    @classmethod
    def disable(cls):
        """Disable all color outputs (for dumb terminals or piping)."""
        cls.RESET = ""
        cls.BOLD = ""
        cls.DIM = ""
        cls.RED = ""
        cls.GREEN = ""
        cls.YELLOW = ""
        cls.BLUE = ""
        cls.MAGENTA = ""
        cls.CYAN = ""
        cls.WHITE = ""


# Auto-enable ANSI and UTF-8 on Windows
if sys.platform == "win32":
    os.system("")  # Enables VT100 in Windows Console if available
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str = "", level: str = "INFO", prefix: str = ""):
    """Structured terminal logging."""
    if prefix:
        print(f"{prefix} {msg}", flush=True)
    else:
        print(msg, flush=True)


def slugify(text: str, max_len: int = 60) -> str:
    """Generate a clean filesystem-friendly slug from title."""
    clean = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII).lower()
    return re.sub(r"[\s_]+", "-", clean.strip())[:max_len].strip("-")


def is_valid_pdf(content: bytes) -> bool:
    """Verify that returned payload is a genuine PDF (>15KB and begins with %PDF)."""
    return len(content) > 15_000 and content[:5].startswith(b"%PDF")


# ==============================================================================
# Constants & Configurations
# ==============================================================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MDPI_ISSN_MAP: Dict[str, str] = {
    "v": "1999-4915",
    "ani": "2076-2615",
    "pathogens": "2076-0817",
    "vaccines": "2076-393X",
    "antibiotics": "2079-6382",
    "vetsci": "2306-7381",
    "ijerph": "1660-4601",
    "cells": "2073-4409",
    "microorganisms": "2076-2607",
}


@dataclass
class PaperRecord:
    doi: str
    title: str = ""
    year: str = ""


# ==============================================================================
# Metadata Resolvers
# ==============================================================================

def fetch_crossref_metadata(doi: str, email: str = "") -> dict:
    """Query Crossref API for bibliographic details (title, year, volume, page)."""
    try:
        params = {"mailto": email} if email else None
        res = requests.get(
            f"https://api.crossref.org/works/{doi}",
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=30,
        )
        if res.status_code != 200:
            return {}
        msg = res.json().get("message", {})
        title_list = msg.get("title") or [""]
        issued = msg.get("issued", {}).get("date-parts") or [[None]]
        container_list = msg.get("container-title") or [""]

        return {
            "title": title_list[0] if title_list else "",
            "year": issued[0][0] if issued and issued[0] else "",
            "volume": msg.get("volume", ""),
            "issue": msg.get("issue", ""),
            "page": msg.get("page", ""),
            "container": container_list[0] if container_list else "",
        }
    except Exception:
        return {}


def query_europe_pmc_pmcid(doi: str) -> Optional[str]:
    """Retrieve PMCID via Europe PMC Search API (works reliably in China networks)."""
    try:
        res = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 5},
            headers=DEFAULT_HEADERS,
            timeout=35,
        )
        if not res.ok:
            return None
        results = res.json().get("resultList", {}).get("result", [])
        for item in results:
            if item.get("pmcid"):
                return item["pmcid"]
    except Exception:
        pass
    return None


# ==============================================================================
# Publisher URL Generators
# ==============================================================================

def generate_publisher_urls(doi: str, meta: dict) -> List[Tuple[str, str]]:
    """Synthesize direct candidate PDF download URLs based on DOI prefixes."""
    urls: List[Tuple[str, str]] = []

    def _add(u: str, tag: str):
        if (u, tag) not in urls:
            urls.append((u, tag))

    # 1. Springer / BMC / SpringerOpen
    if doi.startswith(("10.1007/", "10.1186/")):
        _add(f"https://link.springer.com/content/pdf/{doi}.pdf", "springer-content")
        host = re.sub(r"[^a-z0-9]", "", (meta.get("container") or "").lower())
        if host:
            _add(f"https://{host}.biomedcentral.com/counter/pdf/{doi}.pdf", "bmc-counter")

    # 2. Frontiers
    if doi.startswith("10.3389/"):
        _add(f"https://www.frontiersin.org/articles/{doi}/pdf", "frontiers-doi")
        _add(f"https://www.frontiersin.org/journals/*/articles/{doi}/pdf", "frontiers-j")

    # 3. MDPI
    if doi.startswith("10.3390/"):
        jid = doi.split("/")[1]
        m = re.match(r"^([a-z]+)(\d{2})(\d{2})(\d{4})$", jid)
        if m:
            ab, vol, iss, art = m.groups()
            issn = MDPI_ISSN_MAP.get(ab)
            if issn:
                _add(f"https://www.mdpi.com/{issn}/{int(vol)}/{int(iss)}/{int(art)}/pdf", "mdpi")

    # 4. J-Stage
    if doi.startswith(("10.1292/", "10.1294/", "10.12935/")):
        if meta.get("volume") and meta.get("page"):
            journal = doi.split("/")[1].split(".")[0]
            first_page = meta["page"].split("-")[0]
            issue = str(meta.get("issue", "")).split("S")[0] or "1"
            _add(
                f"https://www.jstage.jst.go.jp/article/{journal}/{meta['volume']}/{issue}/"
                f"{meta['volume']}_{first_page}/_pdf/-char/en",
                "jstage-pattern",
            )

    # 5. Scialert landing page
    if doi.startswith("10.3923/"):
        _add(f"https://scialert.net/abstract/?doi={doi.split('/', 1)[1]}", "scialert-landing")

    return urls


def scrape_jstage_landing_page(doi: str) -> List[str]:
    """Scrape the landing page on J-Stage following doi.org redirection."""
    try:
        res = requests.get(f"https://doi.org/{doi}", headers=DEFAULT_HEADERS, timeout=45, allow_redirects=True)
        if not res.ok:
            return []
        links = re.findall(r'href="(https://www\.jstage\.jst\.go\.jp/article/[^"]+_pdf[^"]*)"', res.text)
        links += ["https://www.jstage.jst.go.jp" + l for l in re.findall(r'href="(/article/[^"]+_pdf[^"]*)"', res.text)]
        return links[:4]
    except Exception:
        return []


def scrape_scialert_pdf(doi: str) -> Optional[bytes]:
    """Scrape Scialert abstract page for PDF link (some are HTML-only)."""
    base_url = f"https://scialert.net/abstract/?doi={doi.split('/', 1)[1]}"
    try:
        res = requests.get(base_url, headers=DEFAULT_HEADERS, timeout=45, verify=False)
        if not res.ok:
            return None
        for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', res.text, flags=re.I):
            pdf_url = href if href.startswith("http") else "https://scialert.net" + href
            content = download_url(pdf_url, verify=False, timeout=60)
            if content:
                return content
    except Exception:
        pass
    return None


def download_url(url: str, verify: bool = True, timeout: int = 60, verbose: bool = False) -> Optional[bytes]:
    """Download content from URL and validate PDF format."""
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True, verify=verify)
        if res.ok and is_valid_pdf(res.content):
            return res.content
        if verbose:
            log(f"    {Colors.DIM}[--] HTTP {res.status_code} len={len(res.content)} {url[:75]}{Colors.RESET}")
    except Exception as e:
        if verbose:
            log(f"    {Colors.DIM}[--] {type(e).__name__} {url[:75]}{Colors.RESET}")
    return None


# ==============================================================================
# PMC Proof-of-Work (Hashcash) Solver
# ==============================================================================

def solve_pmc_hashcash(challenge: str, difficulty: int = 4) -> int:
    """
    Solve PMC Hashcash PoW challenge.
    Finds integer nonce such that sha256(challenge + nonce) starts with `difficulty` zeros.
    """
    target = "0" * difficulty
    nonce = 0
    ch_bytes = challenge.encode("utf-8")
    while True:
        if hashlib.sha256(ch_bytes + str(nonce).encode("utf-8")).hexdigest().startswith(target):
            return nonce
        nonce += 1


def attempt_pmc_download(pmcid: str) -> Tuple[Optional[bytes], str]:
    """
    Single PMC PDF retrieval attempt:
    - Direct PDF download check.
    - Interstitial PoW challenge extraction and nonce solver.
    - Detection of reCAPTCHA escalation.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"

    try:
        res1 = session.get(url, timeout=60)
    except Exception as e:
        return None, f"connect-err: {type(e).__name__}"

    if is_valid_pdf(res1.content):
        return res1.content, "direct"

    # Check for Hashcash challenge
    if "POW_CHALLENGE" in res1.text:
        ch_match = re.search(r'POW_CHALLENGE\s*=\s*"([^"]+)"', res1.text)
        if not ch_match:
            return None, "pow-parse-failed"
        challenge = ch_match.group(1)

        diff_match = re.search(r'POW_DIFFICULTY\s*=\s*"?(\d+)', res1.text)
        difficulty = int(diff_match.group(1)) if diff_match else 4

        cookie_match = re.search(r'POW_COOKIE_NAME\s*=\s*"([^"]+)"', res1.text)
        cookie_name = cookie_match.group(1) if cookie_match else "cloudpmc-viewer-pow"

        nonce = solve_pmc_hashcash(challenge, difficulty)
        session.cookies.set(
            cookie_name,
            f"{challenge},{nonce}",
            path="/",
            domain="pmc.ncbi.nlm.nih.gov",
        )

        try:
            res2 = session.get(url, timeout=90)
            if is_valid_pdf(res2.content):
                return res2.content, "pow-solved"
            return None, "post-pow-not-pdf"
        except Exception as e:
            return None, f"post-pow-err: {type(e).__name__}"

    # Escalated anti-bot check
    if "recaptcha" in res1.text.lower():
        return None, "recaptcha"

    return None, f"status-{res1.status_code}"


# ==============================================================================
# Input Parser & Persistence
# ==============================================================================

def load_records(input_path: Path) -> List[PaperRecord]:
    """Parse paper records from CSV or plain TXT DOI list."""
    records: List[PaperRecord] = []
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Plain text file with one DOI per line
    if input_path.suffix.lower() == ".txt":
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                d = line.strip()
                if d and not d.startswith("#"):
                    records.append(PaperRecord(doi=d))
        return records

    # CSV file
    encodings = ["utf-8-sig", "utf-8", "gbk"]
    rows = []
    for enc in encodings:
        try:
            with open(input_path, "r", encoding=enc, errors="replace", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except Exception:
            continue

    for r in rows:
        # Case-insensitive DOI lookup
        doi_val = ""
        for k in r.keys():
            if k and k.strip().lower() == "doi":
                doi_val = (r[k] or "").strip()
                break
        if not doi_val:
            continue

        title_val = (
            r.get("文献名")
            or r.get("title")
            or r.get("Title")
            or r.get("题名")
            or ""
        ).strip()
        year_val = (
            r.get("年份")
            or r.get("year")
            or r.get("Year")
            or ""
        ).strip()

        records.append(PaperRecord(doi=doi_val, title=title_val, year=year_val))

    return records


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(path: Path, state: dict):
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ==============================================================================
# Main Orchestrator
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OA-PDF-Download: High-reliability Open Access PDF batch harvester."
    )
    parser.add_argument("--input", "-i", required=True, help="Input CSV file or plain TXT list with DOIs")
    parser.add_argument("--outdir", "-o", required=True, help="Directory to save downloaded PDF files")
    parser.add_argument("--state", "-s", default="state.json", help="State file path for resume-safe execution")
    parser.add_argument("--deadline-min", type=int, default=45, help="Overall execution deadline in minutes")
    parser.add_argument("--pmc-delay", nargs=2, type=float, default=[15.0, 30.0],
                        help="Min and Max randomized delay (seconds) between PMC attempts")
    parser.add_argument("--email", default="", help="Contact email for Crossref polite pool")
    parser.add_argument("--skip-pmc", action="store_true", help="Skip Phase B (PMC PoW retrieval)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        Colors.disable()

    input_path = Path(args.input)
    outdir = Path(args.outdir)
    state_path = Path(args.state)

    outdir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_path)

    # 1. Parse Records
    records = load_records(input_path)
    if not records:
        log(f"{Colors.RED}[!] No valid DOI records found in {input_path}{Colors.RESET}")
        sys.exit(1)

    recs_map: Dict[str, PaperRecord] = {r.doi: r for r in records}
    total = len(recs_map)
    todo = [d for d in recs_map if not state.get(d, {}).get("file")]
    completed_count = total - len(todo)

    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  OA-PDF-Download: Harvester Pipeline Initialized{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    log(f"{Colors.WHITE}Total records:{Colors.RESET} {total} | "
        f"{Colors.GREEN}Completed:{Colors.RESET} {completed_count} | "
        f"{Colors.YELLOW}Pending:{Colors.RESET} {len(todo)}")
    log(f"{Colors.WHITE}Output Directory:{Colors.RESET} {outdir.resolve()}")
    log(f"{Colors.WHITE}State Path:{Colors.RESET} {state_path.resolve()}\n")

    def store_pdf(doi: str, content: bytes, source: str):
        rec = recs_map[doi]
        year_str = rec.year or "nd"
        slug_str = slugify(rec.title or doi)
        filename = f"{year_str}_{slug_str}.pdf"
        filepath = outdir / filename

        filepath.write_bytes(content)
        state[doi] = {"file": filename, "source": source}
        save_state(state_path, state)

        kb = len(content) // 1024
        log(f"  {Colors.GREEN}[✓] Saved ({kb} KB):{Colors.RESET} {filename} {Colors.DIM}(via {source}){Colors.RESET}")

    deadline = time.time() + args.deadline_min * 60
    pmcids: Dict[str, Optional[str]] = {}

    # ==========================================================================
    # Phase A: Fast Candidate Resolution
    # ==========================================================================
    log(f"{Colors.BOLD}{Colors.BLUE}▶ Phase A: Fast Direct & Repository Routes (~0.5s pacing){Colors.RESET}")

    idx = 0
    for doi in list(todo):
        if time.time() > deadline:
            log(f"{Colors.YELLOW}[!] Deadline reached during Phase A.{Colors.RESET}")
            break

        idx += 1
        rec = recs_map[doi]

        # Metadata enrichment via Crossref if title or year is missing
        meta = fetch_crossref_metadata(doi, args.email)
        if not rec.title:
            rec.title = meta.get("title") or doi
        if not rec.year:
            rec.year = str(meta.get("year") or "")

        time.sleep(0.3)
        progress = f"[{idx:02d}/{len(todo):02d}]"
        log(f"{Colors.CYAN}{progress} Scanning:{Colors.RESET} {doi} {Colors.DIM}({rec.title[:45]}...){Colors.RESET}")

        downloaded = False

        # 1. Publisher Direct Patterns
        for url, tag in generate_publisher_urls(doi, meta):
            if tag == "scialert-landing":
                continue
            content = download_url(url, verbose=args.verbose)
            if content:
                store_pdf(doi, content, tag)
                downloaded = True
                break
            time.sleep(0.4)

        # 2. Scialert Special Parsing
        if not downloaded and doi.startswith("10.3923/"):
            content = scrape_scialert_pdf(doi)
            if content:
                store_pdf(doi, content, "scialert-scrape")
                downloaded = True

        # 3. J-Stage Landing Redirection Fallback
        if not downloaded and doi.startswith(("10.1292/", "10.1294/", "10.12935/")):
            for j_url in scrape_jstage_landing_page(doi):
                content = download_url(j_url, verbose=args.verbose)
                if content:
                    store_pdf(doi, content, "jstage-landing")
                    downloaded = True
                    break
                time.sleep(0.4)

        if downloaded:
            todo.remove(doi)
            continue

        # 4. Semantic Scholar openAccessPdf Probe
        try:
            res = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "openAccessPdf,isOpenAccess"},
                headers=DEFAULT_HEADERS,
                timeout=30,
            )
            if res.status_code == 429:
                time.sleep(8)
                res = requests.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                    params={"fields": "openAccessPdf"},
                    headers=DEFAULT_HEADERS,
                    timeout=30,
                )
            if res.status_code == 200:
                oa_url = (res.json().get("openAccessPdf") or {}).get("url")
                if oa_url:
                    content = download_url(oa_url, verbose=args.verbose)
                    if content:
                        store_pdf(doi, content, f"s2:{oa_url[:40]}")
                        todo.remove(doi)
                        continue
        except Exception as e:
            if args.verbose:
                log(f"    {Colors.DIM}[s2-err] {type(e).__name__}{Colors.RESET}")

        time.sleep(0.5)

    # ==========================================================================
    # Phase B: PMC with PoW Solver
    # ==========================================================================
    if not args.skip_pmc and todo:
        log(f"\n{Colors.BOLD}{Colors.MAGENTA}▶ Phase B: PMC Harvester with PoW Solver (Adaptive Pacing){Colors.RESET}")
        log(f"{Colors.DIM}Looking up PMCIDs via Europe PMC...{Colors.RESET}")

        for doi in list(todo):
            if time.time() > deadline:
                break
            if doi not in pmcids:
                pmcids[doi] = query_europe_pmc_pmcid(doi)
            time.sleep(0.3)

        pending_pmc = [d for d in todo if pmcids.get(d)]
        log(f"Found {Colors.BOLD}{len(pending_pmc)}{Colors.RESET} items with associated PMCID.")

        round_num = 0
        while pending_pmc and time.time() < deadline:
            round_num += 1
            log(f"\n{Colors.BOLD}{Colors.YELLOW}--- Round {round_num}: Attempting {len(pending_pmc)} PMC items ---{Colors.RESET}")
            unresolved = []

            for doi in pending_pmc:
                if time.time() > deadline:
                    unresolved.append(doi)
                    continue

                delay = random.uniform(*args.pmc_delay)
                pmcid = pmcids[doi]
                log(f"{Colors.DIM}Pacing {delay:.1f}s | Attempting {doi} ({pmcid})...{Colors.RESET}")
                time.sleep(delay)

                try:
                    content, note = attempt_pmc_download(pmcid)
                except Exception as e:
                    content, note = None, f"err:{type(e).__name__}"

                if content:
                    store_pdf(doi, content, f"pmc:{pmcid}")
                else:
                    unresolved.append(doi)
                    log(f"  {Colors.YELLOW}[-] Deferred ({note}):{Colors.RESET} {doi} ({pmcid})")
                    if note == "recaptcha":
                        log(f"{Colors.RED}[!] reCAPTCHA escalation detected. Entering 90s cooldown...{Colors.RESET}")
                        time.sleep(90)

            pending_pmc = unresolved

        todo = [d for d in todo if not state.get(d, {}).get("file")]

    # ==========================================================================
    # Summary Report & Manifest
    # ==========================================================================
    success_dois = [d for d in recs_map if state.get(d, {}).get("file")]
    manifest_path = outdir / "_manifest.csv"

    with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["DOI", "Title", "Year", "Filename", "Source"])
        for d, rec in recs_map.items():
            st = state.get(d, {})
            writer.writerow([
                d,
                rec.title,
                rec.year,
                st.get("file", ""),
                st.get("source", "Not Available via OA"),
            ])

    # Compute source breakdown
    sources_count: Dict[str, int] = {}
    for d in success_dois:
        src = state[d]["source"].split(":")[0].split()[0]
        sources_count[src] = sources_count.get(src, 0) + 1

    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.GREEN}  DOWNLOAD HARVEST SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}")
    log(f"Total Papers: {Colors.BOLD}{total}{Colors.RESET}")
    log(f"Successfully Harvested: {Colors.GREEN}{Colors.BOLD}{len(success_dois)}/{total} "
        f"({(len(success_dois)/total*100):.1f}%){Colors.RESET}")

    if sources_count:
        log("\nBreakdown by Source Channel:")
        for s, c in sorted(sources_count.items(), key=lambda x: -x[1]):
            log(f"  • {s:20s}: {c:3d} PDFs")

    if todo:
        log(f"\n{Colors.YELLOW}Unobtained / Paywalled Papers ({len(todo)}):{Colors.RESET}")
        for d in todo:
            log(f"  {Colors.RED}✗{Colors.RESET} {d} - {Colors.DIM}{recs_map[d].title[:60]}{Colors.RESET}")

    log(f"\nManifest saved to: {Colors.CYAN}{manifest_path.resolve()}{Colors.RESET}")
    log(f"State file saved to: {Colors.CYAN}{state_path.resolve()}{Colors.RESET}\n")


if __name__ == "__main__":
    main()
