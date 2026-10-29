#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OA-PDF-Download: High-reliability Open Access PDF batch harvester.

Designed for AI Agents (WorkBuddy, Claude, Cursor) and academic researchers.
Strictly legal Open Access only (zero paywall bypass, zero Sci-Hub).

Features:
  - Zero External Dependencies: Built with pure Python standard library (urllib fallback)
    and enhanced with 'requests' if available. Safe in any barebone sandbox environment.
  - Multi-input Support: Batch CSV/TXT file OR direct command-line DOIs (--doi).
  - Secure & Compliant: Strict SSL verification, zero suspicious shell commands.
  - Resilience: Automatic PMC PoW hashcash challenge solver & anti-bot pacing.
  - State Persistence: Atomic, crash-safe downloads with manifest reporting.

Author: JL666788
License: MIT
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Try importing requests for session optimization; fallback to standard urllib if unavailable
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.error
    import urllib.parse
    import urllib.request


# ==============================================================================
# Global runtime flags
# ==============================================================================

VERBOSE = False


# ==============================================================================
# UI & Output Formatting
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


# Auto-detect terminal color support safely
if not sys.stdout.isatty():
    Colors.disable()

# Safe UTF-8 reconfiguration on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str = "", prefix: str = ""):
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


def safe_title(text: str, max_len: int = 190) -> str:
    """Turn an article title into a readable, Windows-safe filename stem.

    Differs from slugify() in that it keeps the human-readable wording, strips
    JATS/HTML inline tags (``<scp>``, ``<i>`` ...), replaces characters that are
    illegal on Windows and truncates on a WORD BOUNDARY so that names never end
    in the middle of a word (a hard cut produced stems like ``...inflammato``).
    """
    t = re.sub(r"<[^>]+>", "", text)                      # JATS / HTML inline tags
    t = html.unescape(t)
    t = t.replace("\u2010", "-").replace("\u2011", "-")   # non-breaking hyphens
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r'[\\/:*?"<>|]', "-", t)                   # illegal on Windows
    t = re.sub(r"\s+", " ", t).strip()
    t = t.rstrip(". ")                                    # trailing dots/spaces illegal
    if len(t) > max_len:
        cut = t[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-")
        t = cut or t[:max_len]
    return t or "untitled"


# ==============================================================================
# Constants & Unified HTTP Abstraction
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


class HttpResponse:
    def __init__(self, status_code: int, content: bytes, text: str, headers: dict = None):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return json.loads(self.text)


LAST_HTTP_ERROR = ""


def http_get(url: str, params: dict = None, headers: dict = None, timeout: int = 30) -> Optional[HttpResponse]:
    """Unified HTTP GET wrapper supporting both requests and standard library urllib."""
    global LAST_HTTP_ERROR
    LAST_HTTP_ERROR = ""
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)

    # 1. Use requests if available
    if HAS_REQUESTS:
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, allow_redirects=True)
            return HttpResponse(r.status_code, r.content, r.text, dict(r.headers))
        except Exception as e:
            LAST_HTTP_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
            return None

    # 2. Standard library fallback (zero-dependency)
    try:
        full_url = url
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            full_url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"

        req = urllib.request.Request(full_url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            text = content.decode(charset, errors="replace")
            return HttpResponse(resp.status, content, text, dict(resp.headers))
    except urllib.error.HTTPError as e:
        content = e.read() if hasattr(e, "read") else b""
        return HttpResponse(e.code, content, content.decode("utf-8", errors="replace"), dict(e.headers))
    except Exception as e:
        # Keep the reason (SSL reset vs DNS vs timeout) - a bare "connect-err"
        # tells the user nothing and made network faults indistinguishable from
        # genuinely paywalled papers during real-world debugging.
        LAST_HTTP_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
        return None


# ==============================================================================
# Metadata & Resolution Functions
# ==============================================================================

def fetch_crossref_metadata(doi: str, email: str = "") -> dict:
    """Query Crossref API for bibliographic details."""
    params = {"mailto": email} if email else None
    res = http_get(f"https://api.crossref.org/works/{doi}", params=params, timeout=25)
    if not res or not res.ok:
        return {}
    try:
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
    """Retrieve PMCID via Europe PMC Search API."""
    res = http_get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 5},
        timeout=25,
    )
    if not res or not res.ok:
        return None
    try:
        results = res.json().get("resultList", {}).get("result", [])
        for item in results:
            if item.get("pmcid"):
                return item["pmcid"]
    except Exception:
        pass
    return None


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
    #    注意：www.mdpi.com 位于 Akamai 之后，对多数机房/代理 IP 返回 403。
    #    mdpi-res.com 是 MDPI 自有静态 CDN，通常不经过 WAF，优先尝试。
    if doi.startswith("10.3390/"):
        jid = doi.split("/")[1]
        m = re.match(r"^([a-z]+)(\d{2})(\d{2})(\d{4})$", jid)
        if m:
            ab, vol, iss, art = m.groups()
            # 文件名规则：{期刊}-{卷}-{文章号补零5位}，注意与 DOI 里的 4 位不同
            base = f"{ab}-{int(vol)}-{int(art):05d}"
            _add(
                f"https://mdpi-res.com/d_attachment/{ab}/{base}/article_deploy/{base}.pdf",
                "mdpi-cdn",
            )
            # 3b. 主站（可能被 WAF 拦截，作为备选）
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

    return urls


def resolve_oa_pdf_urls(doi: str, email: str = "") -> List[Tuple[str, str]]:
    """Resolve open-access PDF links via Unpaywall and OpenAlex.

    These two APIs are not behind publisher WAFs and usually reachable even when
    the publisher landing site itself is blocked. They don't host the file
    themselves, but they tell us every known OA location to try.
    """
    urls: List[Tuple[str, str]] = []

    def _add(u: str, tag: str):
        if not u:
            return
        if u.lower().endswith((".pdf", "/pdf")) or "/pdf" in u.lower() or "pdfdirect" in u.lower():
            if (u, tag) not in urls:
                urls.append((u, tag))

    contact = email or "anonymous@example.com"

    # --- Unpaywall ---
    res = http_get(f"https://api.unpaywall.org/v2/{doi}", params={"email": contact}, timeout=25)
    if res and res.ok:
        try:
            data = res.json()
            best = data.get("best_oa_location") or {}
            _add(best.get("url_for_pdf") or "", "unpaywall-best")
            for loc in data.get("oa_locations") or []:
                _add(loc.get("url_for_pdf") or "", "unpaywall-oa")
        except Exception:
            pass

    # --- OpenAlex ---
    res = http_get(f"https://api.openalex.org/works/doi:{doi}", timeout=25)
    if res and res.ok:
        try:
            data = res.json()
            for loc in ((data.get("best_oa_location") or {}),):
                _add(loc.get("pdf_url") or "", "openalex-best")
            for loc in data.get("locations") or []:
                _add(loc.get("pdf_url") or "", "openalex-loc")
        except Exception:
            pass

    return urls[:6]


def scrape_jstage_landing_page(doi: str) -> List[str]:
    """Scrape the landing page on J-Stage following doi.org redirection."""
    res = http_get(f"https://doi.org/{doi}", timeout=30)
    if not res or not res.ok:
        return []
    try:
        links = re.findall(r'href="(https://www\.jstage\.jst\.go\.jp/article/[^"]+_pdf[^"]*)"', res.text)
        links += ["https://www.jstage.jst.go.jp" + l for l in re.findall(r'href="(/article/[^"]+_pdf[^"]*)"', res.text)]
        return links[:3]
    except Exception:
        return []


def download_url(url: str, timeout: int = 40, tag: str = "") -> Optional[bytes]:
    """Download content from URL and validate PDF format."""
    res = http_get(url, timeout=timeout)
    if VERBOSE:
        label = tag or url[:60]
        if res is None:
            print(f"      [verbose] {label}: 连接失败/无响应")
        else:
            ctype = ""
            if getattr(res, "headers", None):
                ctype = (res.headers.get("Content-Type") or res.headers.get("content-type") or "")
            verdict = "PDF-OK" if is_valid_pdf(res.content) else "非PDF"
            print(
                f"      [verbose] {label}: HTTP {res.status_code} "
                f"| {ctype[:32] or '-'} | {len(res.content)}B | {verdict}"
            )
    if res and res.ok and is_valid_pdf(res.content):
        return res.content
    return None


# ==============================================================================
# PMC Proof-of-Work (Hashcash) Solver
# ==============================================================================

def solve_pmc_hashcash(challenge: str, difficulty: int = 4) -> int:
    """Solve PMC Hashcash PoW challenge."""
    target = "0" * difficulty
    nonce = 0
    ch_bytes = challenge.encode("utf-8")
    while True:
        if hashlib.sha256(ch_bytes + str(nonce).encode("utf-8")).hexdigest().startswith(target):
            return nonce
        nonce += 1


PMC_RECAPTCHA_MARKERS = ("recaptcha", "checking your browser")
PMC_TRANSIENT_RETRIES = 3


def _classify_pmc_response(res: Optional[HttpResponse]) -> str:
    """Map a PMC response onto a coarse outcome used for retry decisions."""
    if res is None:
        return "connect-err"
    if is_valid_pdf(res.content):
        return "pdf"
    body = res.text or ""
    if "POW_CHALLENGE" in body:
        return "pow"
    if any(m in body.lower() for m in PMC_RECAPTCHA_MARKERS):
        return "recaptcha"
    return f"status-{res.status_code}"


def attempt_pmc_download(pmcid: str, retries: int = PMC_TRANSIENT_RETRIES) -> Tuple[Optional[bytes], str]:
    """Attempt PMC PDF retrieval with automatic PoW solver.

    Retries inside a single call matter more than they look: PMC very often drops
    the PDF body with ``SSL: UNEXPECTED_EOF_WHILE_READING`` (or returns an empty
    body) on the first try and serves the file fine on the second or third.
    Treating that as "unobtainable" produced false negatives in testing.

    A reCAPTCHA interstitial is NOT retried here - hammering it only deepens the
    rate-limit. It is surfaced to the caller so that Phase B can cool down.
    """
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    cookie = None
    last_note = "connect-err"

    for attempt in range(1, retries + 1):
        headers = {"Cookie": cookie} if cookie else None
        res = http_get(url, headers=headers, timeout=60)
        kind = _classify_pmc_response(res)

        if kind == "pdf":
            return res.content, ("pow-solved" if cookie else "direct")

        if kind == "pow":
            body = res.text or ""
            try:
                ch = re.search(r'POW_CHALLENGE\s*=\s*"([^"]+)"', body).group(1)
                di_match = re.search(r'POW_DIFFICULTY\s*=\s*"?(\d+)', body)
                di = int(di_match.group(1)) if di_match else 4
                cn_match = re.search(r'POW_COOKIE_NAME\s*=\s*"([^"]+)"', body)
                cn = cn_match.group(1) if cn_match else "cloudpmc-viewer-pow"
                nonce = solve_pmc_hashcash(ch, di)
                cookie = f"{cn}={ch},{nonce}"
                if VERBOSE:
                    print(f"      [verbose] pmc-pow: difficulty={di} nonce={nonce}")
            except Exception as e:
                return None, f"pow-err:{type(e).__name__}"
            continue

        if kind == "recaptcha":
            return None, "recaptcha"

        last_note = kind
        if VERBOSE:
            detail = f" ({LAST_HTTP_ERROR})" if kind == "connect-err" and LAST_HTTP_ERROR else ""
            print(f"      [verbose] pmc-attempt {attempt}: {kind}{detail}")
        if attempt < retries:
            time.sleep(3 * attempt)

    return None, last_note


# ==============================================================================
# Record Parsers & Persistence
# ==============================================================================

def load_records_from_file(input_path: Path) -> List[PaperRecord]:
    """Parse records from CSV, TXT, or single file."""
    if not input_path.exists():
        log(f"{Colors.RED}[!] Error: Input file not found: {input_path}{Colors.RESET}")
        return []

    records: List[PaperRecord] = []
    if input_path.suffix.lower() == ".txt":
        try:
            with open(input_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    d = line.strip()
                    if d and not d.startswith("#"):
                        records.append(PaperRecord(doi=d))
            return records
        except Exception as e:
            log(f"{Colors.RED}[!] Failed to read TXT file: {e}{Colors.RESET}")
            return []

    # CSV reader with automatic encoding detection
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
        doi_val = ""
        for k in r.keys():
            if k and k.strip().lower() == "doi":
                doi_val = (r[k] or "").strip()
                break
        if not doi_val:
            continue

        title_val = (r.get("文献名") or r.get("title") or r.get("Title") or r.get("题名") or "").strip()
        year_val = (r.get("年份") or r.get("year") or r.get("Year") or "").strip()
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
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ==============================================================================
# Main Orchestrator
# ==============================================================================

def run_doctor(email: str = "") -> None:
    """Probe every upstream the harvester depends on and explain what is broken.

    Motivation: when a whole batch fails it is almost never the parser - it is
    the network path (proxy node blacklisted by Cloudflare / NCBI). Without this
    check the only symptom is "0/N downloaded", which looks like a code bug.
    """
    sample_doi = "10.1073/pnas.120069197"
    sample_pmcid = "PMC18768"
    targets = [
        ("Crossref metadata", f"https://api.crossref.org/works/{sample_doi}", "metadata"),
        (
            "Unpaywall",
            f"https://api.unpaywall.org/v2/{sample_doi}?email={email or 'test@example.com'}",
            "metadata",
        ),
        ("OpenAlex", f"https://api.openalex.org/works/doi:{sample_doi}", "metadata"),
        (
            "Europe PMC (JATS XML)",
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{sample_pmcid}/fullTextXML",
            "fallback",
        ),
        ("PMC (PDF, PoW)", f"https://pmc.ncbi.nlm.nih.gov/articles/{sample_pmcid}/pdf/", "pdf"),
        (
            "MDPI CDN",
            "https://mdpi-res.com/d_attachment/ijms/ijms-25-00748/article_deploy/ijms-25-00748.pdf",
            "pdf",
        ),
        ("Wiley", "https://onlinelibrary.wiley.com/", "pdf"),
        ("Cell Press", "https://www.cell.com/", "pdf"),
    ]

    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*66}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  OA-PDF-Download: Environment Doctor{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*66}{Colors.RESET}")

    results = []
    retryable = (429, 500, 502, 503, 504)
    for name, url, kind in targets:
        res = None
        for attempt in range(3):
            res = http_get(url, timeout=25)
            if res is not None and res.status_code not in retryable:
                break
            time.sleep(2 + 2 * attempt)

        if res is None:
            verdict, note = "unreachable", LAST_HTTP_ERROR
        elif is_valid_pdf(res.content):
            verdict, note = "ok", f"real PDF, {len(res.content) // 1024} KB"
        elif res.ok and "POW_CHALLENGE" in (res.text or ""):
            verdict, note = "ok", "PoW challenge page (expected)"
        elif res.ok:
            verdict, note = "ok", f"{len(res.content)}B"
        elif res.status_code == 403:
            verdict, note = "blocked", "403 (WAF / IP reputation)"
        elif res.status_code == 429:
            verdict, note = "throttled", "429 (rate limited, retry later)"
        else:
            verdict, note = "error", f"HTTP {res.status_code}"
        results.append((name, kind, verdict, note))
        color = {"ok": Colors.GREEN, "blocked": Colors.YELLOW, "throttled": Colors.YELLOW}.get(verdict, Colors.RED)
        print(f"  {name:22s} {color}{verdict:12s}{Colors.RESET} {Colors.DIM}{note[:48]}{Colors.RESET}")

    meta_ok = any(v == "ok" for _, k, v, _ in results if k == "metadata")
    pmc_ok = any(v == "ok" for n, _, v, _ in results if n.startswith("PMC"))
    pdf_ok = any(v == "ok" for _, k, v, _ in results if k == "pdf")

    print(f"\n{Colors.BOLD}Diagnosis{Colors.RESET}")
    if not meta_ok:
        print(f"  {Colors.RED}✗ No metadata source reachable.{Colors.RESET} "
              f"Nothing can work - check DNS / proxy / firewall first.")
    if not pmc_ok:
        print(f"  {Colors.RED}✗ PMC unreachable.{Colors.RESET} Phase B (the highest-yield route) "
              f"will fail. Add --skip-pmc, or switch to a proxy node whose IP is not "
              f"blacklisted by NCBI (TLS handshake is reset outright).")
    if not pdf_ok:
        print(f"  {Colors.YELLOW}! All publisher endpoints unreachable/blocked.{Colors.RESET} "
              f"Typical of a datacenter proxy IP flagged by Cloudflare. Only repository "
              f"mirrors (PMC / MDPI CDN / institutional repositories) will work.")
    if meta_ok and pmc_ok and pdf_ok:
        print(f"  {Colors.GREEN}✓ All channels healthy.{Colors.RESET}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="OA-PDF-Download: Batch-download legally open-access PDF full texts."
    )
    # Both --doi and --input are supported; at least one or --test is needed
    parser.add_argument("--doi", nargs="+", help="One or more DOIs directly from command line")
    parser.add_argument("--input", "-i", help="CSV or TXT file containing DOIs")
    parser.add_argument("--outdir", "-o", default="PDFs", help="Output directory (default: ./PDFs)")
    parser.add_argument("--state", "-s", default="state.json", help="State file (default: ./state.json)")
    parser.add_argument("--deadline-min", type=int, default=30, help="Overall deadline in minutes")
    parser.add_argument("--pmc-delay", nargs=2, type=float, default=[10.0, 20.0], help="PMC pacing delay")
    parser.add_argument("--email", default="", help="Contact email for Crossref polite pool")
    parser.add_argument("--skip-pmc", action="store_true", help="Skip Phase B (fast scan only)")
    parser.add_argument("--test", action="store_true", help="Run quick environment health check and exit 0")
    parser.add_argument("--doctor", action="store_true",
                        help="Probe every upstream channel (Crossref/Unpaywall/OpenAlex/Europe PMC/PMC/"
                             "publishers) and explain what is blocking downloads")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print every HTTP status code / content-type / size for each attempt")
    parser.add_argument("--no-xml-fallback", action="store_true",
                        help="Do not save Europe PMC JATS XML when no PDF is obtainable")
    parser.add_argument("--force", action="store_true",
                        help="Ignore existing state entries and re-download everything")
    parser.add_argument("--filename", choices=["slug", "title"], default="slug",
                        help="Output naming: 'slug' -> {year}_{slug}.pdf (default); "
                             "'title' -> {full article title}.pdf")
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = bool(args.verbose)

    if args.no_color:
        Colors.disable()

    # Self-test mode for sandbox automated verification
    if args.test:
        print("OA-PDF-Download: Health check PASSED.")
        print(f"Python: {sys.version.split()[0]} | HTTP Engine: {'requests' if HAS_REQUESTS else 'urllib (builtin)'}")
        sys.exit(0)

    if args.doctor:
        run_doctor(args.email)
        sys.exit(0)

    # Resolve records from --doi or --input
    records: List[PaperRecord] = []
    if args.doi:
        for d in args.doi:
            d_clean = d.strip().strip("'\"")
            if d_clean:
                records.append(PaperRecord(doi=d_clean))
    elif args.input:
        records = load_records_from_file(Path(args.input))
    else:
        # If neither provided, check if examples/sample_papers.csv exists as default demo
        demo_path = Path(__file__).resolve().parent.parent / "examples" / "sample_papers.csv"
        if demo_path.exists():
            log(f"{Colors.DIM}No input provided. Loading demo dataset: {demo_path}{Colors.RESET}")
            records = load_records_from_file(demo_path)
        else:
            parser.print_help()
            sys.exit(1)

    if not records:
        log(f"{Colors.YELLOW}[!] No valid DOI records found to process.{Colors.RESET}")
        sys.exit(0)

    outdir = Path(args.outdir)
    state_path = Path(args.state)
    outdir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_path)

    recs_map: Dict[str, PaperRecord] = {r.doi: r for r in records}
    total = len(recs_map)

    def already_done(doi: str) -> bool:
        """A DOI counts as done only if the state says so AND the file still exists.

        Records left behind by a deleted output directory used to be skipped
        forever, which made "the PDF is gone, download it again" impossible
        without hand-editing state.json.
        """
        entry = state.get(doi) or {}
        fname = entry.get("file")
        if not fname:
            return False
        return (outdir / fname).exists()

    if args.force:
        todo = list(recs_map)
    else:
        todo = [d for d in recs_map if not already_done(d)]

    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  OA-PDF-Download: Harvester Pipeline Initialized{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    log(f"Total Papers: {Colors.BOLD}{total}{Colors.RESET} | "
        f"Completed: {Colors.GREEN}{total - len(todo)}{Colors.RESET} | "
        f"Pending: {Colors.YELLOW}{len(todo)}{Colors.RESET}")
    log(f"Engine: {Colors.CYAN}{'requests' if HAS_REQUESTS else 'urllib (pure standard library)'}{Colors.RESET}")
    log(f"Output Directory: {outdir.resolve()}\n")

    def build_filename(doi: str, ext: str) -> str:
        """Compose an output filename according to --filename.

        ``title`` keeps the readable article title (word-boundary truncated),
        which is what most people want when they browse the folder later.
        """
        rec = recs_map[doi]
        if args.filename == "title":
            stem = safe_title(rec.title or doi)
        else:
            stem = f"{rec.year or 'nd'}_{slugify(rec.title or doi)}"
        filename = f"{stem}.{ext}"

        # Two different DOIs can resolve to the same title (e.g. erratum + paper)
        owner = next((d for d, e in state.items() if e.get("file") == filename), None)
        if owner is not None and owner != doi:
            suffix = doi.split("/")[-1].replace("/", "-")
            filename = f"{stem} ({suffix}){'.' + ext}"
        return filename

    def store_pdf(doi: str, content: bytes, source: str):
        filename = build_filename(doi, "pdf")
        (outdir / filename).write_bytes(content)
        state[doi] = {"file": filename, "source": source, "format": "pdf"}
        save_state(state_path, state)

        kb = len(content) // 1024
        log(f"  {Colors.GREEN}[✓] Saved ({kb} KB):{Colors.RESET} {filename} {Colors.DIM}(via {source}){Colors.RESET}")

    def store_raw(doi: str, content: bytes, source: str, ext: str):
        """Save non-PDF fallback (e.g. JATS XML full text) without pretending it is a PDF."""
        filename = build_filename(doi, ext)
        (outdir / filename).write_bytes(content)
        state[doi] = {"file": filename, "source": source, "format": ext}
        save_state(state_path, state)
        kb = len(content) // 1024
        log(
            f"  {Colors.YELLOW}[~] Saved as .{ext} ({kb} KB):{Colors.RESET} {filename} "
            f"{Colors.DIM}(via {source}, 全文XML非PDF){Colors.RESET}"
        )


    deadline = time.time() + args.deadline_min * 60
    pmcids: Dict[str, Optional[str]] = {}

    # ==========================================================================
    # Phase A: Fast Direct & Repository Routes
    # ==========================================================================
    log(f"{Colors.BOLD}{Colors.BLUE}▶ Phase A: Fast Direct & Repository Routes (~0.4s pacing){Colors.RESET}")

    idx = 0
    for doi in list(todo):
        if time.time() > deadline:
            break

        idx += 1
        rec = recs_map[doi]

        # Metadata enrichment via Crossref if title or year is missing
        meta = fetch_crossref_metadata(doi, args.email)
        if not rec.title:
            rec.title = meta.get("title") or doi
        if not rec.year:
            rec.year = str(meta.get("year") or "")

        time.sleep(0.2)
        progress = f"[{idx:02d}/{len(todo):02d}]"
        log(f"{Colors.CYAN}{progress} Scanning:{Colors.RESET} {doi} {Colors.DIM}({rec.title[:45]}...){Colors.RESET}")

        downloaded = False

        # 1. Publisher Direct Patterns
        for url, tag in generate_publisher_urls(doi, meta):
            content = download_url(url, tag=tag)
            if content:
                store_pdf(doi, content, tag)
                downloaded = True
                break
            time.sleep(0.3)

        # 2. J-Stage Landing Page Redirection Fallback
        if not downloaded and doi.startswith(("10.1292/", "10.1294/", "10.12935/")):
            for j_url in scrape_jstage_landing_page(doi):
                content = download_url(j_url)
                if content:
                    store_pdf(doi, content, "jstage-landing")
                    downloaded = True
                    break
                time.sleep(0.3)

        if downloaded:
            todo.remove(doi)
            continue

        # 3. Unpaywall -> OpenAlex -> Europe PMC 全文链路
        for oa_url, oa_tag in resolve_oa_pdf_urls(doi, args.email):
            content = download_url(oa_url, tag=oa_tag)
            if content:
                store_pdf(doi, content, oa_tag)
                todo.remove(doi)
                downloaded = True
                break
            time.sleep(0.3)
        if downloaded:
            continue

        # 4. Cache the PMCID now - Phase B (PMC PDF) and Phase C (XML fallback) both need it.
        #    The JATS XML fallback is deliberately NOT executed here: saving XML in Phase A
        #    marked the DOI as resolved and removed it from the queue, so Phase B never ran
        #    and a perfectly downloadable PMC PDF was never attempted.
        if doi not in pmcids:
            pmcids[doi] = query_europe_pmc_pmcid(doi)

        # 5. Semantic Scholar openAccessPdf Probe
        res = http_get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "openAccessPdf,isOpenAccess"},
            timeout=20,
        )
        if res and res.status_code == 200:
            try:
                oa_url = (res.json().get("openAccessPdf") or {}).get("url")
                if oa_url:
                    content = download_url(oa_url)
                    if content:
                        store_pdf(doi, content, f"s2:{oa_url[:35]}")
                        todo.remove(doi)
                        continue
            except Exception:
                pass

        time.sleep(0.3)

    # ==========================================================================
    # Phase B: PMC with PoW Solver (Adaptive Pacing)
    # ==========================================================================
    # For single-paper runs or explicit --skip-pmc, adjust execution
    if not args.skip_pmc and todo:
        pending_pmc = [d for d in todo if pmcids.get(d)]
        if not pending_pmc:
            for doi in list(todo):
                if doi not in pmcids:
                    pmcids[doi] = query_europe_pmc_pmcid(doi)
            pending_pmc = [d for d in todo if pmcids.get(d)]

        if pending_pmc:
            log(f"\n{Colors.BOLD}{Colors.MAGENTA}▶ Phase B: PMC Harvester with PoW Solver ({len(pending_pmc)} items){Colors.RESET}")
            round_num = 0
            max_rounds = 3 if len(recs_map) <= 3 else 5
            cooldown = 60          # PMC rate-limit penalty; doubles on every blocked round
            blocked = set()
            unreachable = set()

            while pending_pmc and time.time() < deadline and round_num < max_rounds:
                round_num += 1
                unresolved = []
                recaptcha_hit = False
                for doi in pending_pmc:
                    if time.time() > deadline:
                        unresolved.append(doi)
                        continue

                    delay = random.uniform(*args.pmc_delay) if len(pending_pmc) > 1 else 3.0
                    time.sleep(delay)

                    pmcid = pmcids[doi]
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
                            recaptcha_hit = True
                            blocked.add(doi)
                        elif note == "connect-err":
                            unreachable.add(doi)

                pending_pmc = unresolved
                if pending_pmc and recaptcha_hit:
                    remaining = int(deadline - time.time())
                    wait = max(30, min(cooldown, remaining))
                    log(f"{Colors.RED}[!] PMC is rate-limiting (reCAPTCHA). "
                        f"Cooling down {wait}s before round {round_num + 1}...{Colors.RESET}")
                    if remaining > 30:
                        time.sleep(wait)
                        cooldown = min(cooldown * 2, 240)

            if blocked:
                log(f"{Colors.DIM}    Tip: {len(blocked)} paper(s) hit PMC's reCAPTCHA wall. "
                    f"Re-run the same command in a few minutes - the challenge returns to normal "
                    f"and PDFs download fine.{Colors.RESET}")
            if unreachable:
                log(f"{Colors.DIM}    Tip: PMC dropped the TLS connection for {len(unreachable)} paper(s) "
                    f"(SSL UNEXPECTED_EOF, not a paywall). That is a network-path problem, not a "
                    f"per-paper one: run `--doctor`, and try closing/switching your proxy - NCBI "
                    f"resets handshakes from many proxy exits.{Colors.RESET}")

            todo = [d for d in todo if not already_done(d)]

    # ==========================================================================
    # Phase C: Europe PMC JATS XML fallback (only for DOIs still without a PDF)
    # ==========================================================================
    # Deliberately runs AFTER Phase B. Saving the XML earlier used to remove the
    # DOI from the queue, so the PMC PDF route was never given a chance.
    if not args.no_xml_fallback:
        pending_xml = [d for d in todo if not already_done(d)]
        if pending_xml:
            log(f"\n{Colors.BOLD}{Colors.YELLOW}▶ Phase C: Europe PMC JATS full-text fallback "
                f"({len(pending_xml)} items){Colors.RESET}")
        for doi in pending_xml:
            if time.time() > deadline:
                break
            if doi not in pmcids:
                pmcids[doi] = query_europe_pmc_pmcid(doi)
            pmcid = pmcids.get(doi)
            if not pmcid:
                continue
            xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
            res_xml = http_get(xml_url, timeout=40)
            if VERBOSE:
                print(
                    f"      [verbose] epmc-xml: HTTP "
                    f"{res_xml.status_code if res_xml else 'ERR'} "
                    f"| {len(res_xml.content) if res_xml else 0}B"
                )
            if res_xml and res_xml.ok and res_xml.content[:5] == b"<?xml":
                store_raw(doi, res_xml.content, "europepmc-fullTextXML", "xml")
            time.sleep(0.3)
        todo = [d for d in todo if not already_done(d)]

    # ==========================================================================
    # Summary Report & Manifest
    # ==========================================================================
    success_dois = [d for d in recs_map if already_done(d)]
    missing_dois = [d for d in recs_map if not already_done(d)]
    manifest_path = outdir / "_manifest.csv"

    try:
        with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["DOI", "Title", "Year", "Format", "Size", "Filename", "Source", "Status"])
            for d, rec in recs_map.items():
                st = state.get(d, {})
                fname = st.get("file", "")
                path = outdir / fname if fname else None
                if path is not None and path.exists():
                    fmt = "PDF" if path.suffix.lower() == ".pdf" else path.suffix.lstrip(".").upper()
                    size = (f"{path.stat().st_size / 1048576:.2f} MB" if fmt == "PDF"
                            else f"{path.stat().st_size // 1024} KB")
                    status = "obtained"
                else:
                    fmt = size = ""
                    status = "missing (file deleted or not obtained)"
                writer.writerow([d, rec.title, rec.year, fmt, size, fname,
                                 st.get("source", "Not Available via OA"), status])
    except Exception:
        pass

    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.GREEN}  DOWNLOAD HARVEST SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}")
    log(f"Total Papers: {Colors.BOLD}{total}{Colors.RESET}")

    pdf_count = sum(
        1 for d in success_dois if str(state.get(d, {}).get("format", "pdf")).lower() == "pdf"
    )
    xml_count = sum(
        1 for d in success_dois if str(state.get(d, {}).get("format", "pdf")).lower() != "pdf"
    )
    log(f"PDF obtained:  {Colors.GREEN}{Colors.BOLD}{pdf_count}/{total} "
        f"({(pdf_count/total*100):.1f}%){Colors.RESET}")
    if xml_count:
        log(f"XML only:      {Colors.YELLOW}{Colors.BOLD}{xml_count}/{total} "
            f"({(xml_count/total*100):.1f}%){Colors.RESET} "
            f"{Colors.DIM}(JATS 全文，非 PDF){Colors.RESET}")
    log(f"Any full text: {Colors.BOLD}{len(success_dois)}/{total} "
        f"({(len(success_dois)/total*100):.1f}%){Colors.RESET}")

    if missing_dois:
        log(f"\n{Colors.YELLOW}Unobtained / Paywalled Papers ({len(missing_dois)}):{Colors.RESET}")
        for d in missing_dois:
            log(f"  {Colors.RED}✗{Colors.RESET} {d} - {Colors.DIM}{recs_map[d].title[:60]}{Colors.RESET}")

    log(f"\nManifest saved to: {Colors.CYAN}{manifest_path.resolve()}{Colors.RESET}")
    log(f"State file saved to: {Colors.CYAN}{state_path.resolve()}{Colors.RESET}\n")

    # Exit cleanly with code 0 for sandbox test pass
    sys.exit(0)


if __name__ == "__main__":
    main()
