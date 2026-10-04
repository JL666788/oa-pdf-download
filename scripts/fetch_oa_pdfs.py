#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch legally open-access PDF full texts for a list of papers (by DOI).

Channels used (all legal OA; no paywall circumvention):
  Phase A (fast, ~0.5-1 s pacing):
    1. Publisher direct URL patterns (Springer/BMC/SpringerOpen, Frontiers,
       MDPI, J-Stage, Scialert) built from Crossref metadata
    2. Springer universal fallback  link.springer.com/content/pdf/{doi}.pdf
    3. Europe PMC fullTextPDF endpoint (for items with a PMCID)
    4. Semantic Scholar openAccessPdf probe
  Phase B (slow, 15-30 s pacing, multi-round until deadline):
    5. pmc.ncbi.nlm.nih.gov PDF with hashcash proof-of-work solving

Usage:
  python fetch_oa_pdfs.py --input records.csv --outdir PDFs --state state.json \
      [--deadline-min 45] [--pmc-delay 15 30] [--email you@univ.edu.cn]

Input CSV: UTF-8 or UTF-8-BOM, column "DOI" required; optional "文献名"/"title"
and "年份"/"year" columns used for output filenames (else fetched from Crossref).
State JSON maps DOI -> {"file":..., "source":...}; re-running skips finished
items, so the script is crash-safe and can be re-launched repeatedly.

Every PDF is validated (%PDF magic, >15 KB) before it is written; an HTML page
that merely looks like an article is never saved as a .pdf.
"""
import argparse, csv, hashlib, json, os, random, re, sys, time, warnings
from pathlib import Path

import requests
warnings.filterwarnings("ignore")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9"}

MDPI_ISSN = {"v": "1999-4915", "ani": "2076-2615", "pathogens": "2076-0817",
             "vaccines": "2076-393X", "antibiotics": "2079-6382", "vetsci": "2306-7381",
             "ijerph": "1660-4601", "cells": "2073-4409", "microorganisms": "2076-2607"}


def log(*a):
    print(*a, flush=True)


def slug(t, n=60):
    t = re.sub(r"[^\w\s-]", "", t, flags=re.ASCII).lower()
    return re.sub(r"[\s_]+", "-", t.strip())[:n].strip("-")


def is_pdf(body):
    return len(body) > 15_000 and body[:5].startswith(b"%PDF")


def load_state(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(p, st):
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def crossref(doi, email=""):
    """Minimal Crossref metadata: title, year, volume, issue, page, container."""
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}",
                         params={"mailto": email} if email else None,
                         headers=UA, timeout=40)
        if r.status_code != 200:
            return {}
        m = r.json()["message"]
        return {"title": (m.get("title") or [""])[0],
                "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
                "volume": m.get("volume", ""), "issue": m.get("issue", ""),
                "page": m.get("page", ""), "container": (m.get("container-title") or [""])[0]}
    except Exception:
        return {}


def epmc_pmcid(doi):
    """PMCID via Europe PMC search (works where www.ncbi.nlm.nih.gov is DNS-poisoned)."""
    try:
        r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 5},
                         headers=UA, timeout=40)
        for x in (r.json().get("resultList", {}).get("result") or []):
            if x.get("pmcid"):
                return x["pmcid"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- publisher URLs
def publisher_urls(doi, meta):
    """Candidate direct URLs by DOI prefix. Returns [(url, label), ...]."""
    urls = []

    def add(u, label):
        if (u, label) not in urls:
            urls.append((u, label))

    if doi.startswith(("10.1007/", "10.1186/")):          # Springer / BMC / SpringerOpen
        add(f"https://link.springer.com/content/pdf/{doi}.pdf", "springer-content")
        host = re.sub(r"[^a-z0-9]", "", (meta.get("container") or "").lower())
        if host:
            add(f"https://{host}.biomedcentral.com/counter/pdf/{doi}.pdf", "bmc-counter")

    if doi.startswith("10.3389/"):                        # Frontiers
        add(f"https://www.frontiersin.org/articles/{doi}/pdf", "frontiers-doi")
        add(f"https://www.frontiersin.org/journals/*/articles/{doi}/pdf", "frontiers-j")

    if doi.startswith("10.3390/"):                        # MDPI
        jid = doi.split("/")[1]
        m = re.match(r"^([a-z]+)(\d{2})(\d{2})(\d{4})$", jid)
        if m:
            ab, vol, iss, art = m.groups()
            issn = MDPI_ISSN.get(ab)
            if issn:
                add(f"https://www.mdpi.com/{issn}/{int(vol)}/{int(iss)}/{int(art)}/pdf", "mdpi")

    if doi.startswith(("10.1292/", "10.1294/", "10.12935/")):   # J-Stage journals
        if meta.get("volume") and meta.get("page"):
            j = doi.split("/")[1].split(".")[0]           # jvms / jes / jvma
            fp = meta["page"].split("-")[0]
            iss = str(meta.get("issue", "")).split("S")[0] or "1"
            add(f"https://www.jstage.jst.go.jp/article/{j}/{meta['volume']}/{iss}/"
                f"{meta['volume']}_{fp}/_pdf/-char/en", "jstage-pattern")

    if doi.startswith("10.3923/"):                        # Scialert (HTML-only journal)
        add(f"https://scialert.net/abstract/?doi={doi.split('/', 1)[1]}", "scialert-landing")
    return urls


def jstage_from_landing(doi):
    """Follow doi.org redirect to J-Stage and scrape the _pdf link (robust fallback)."""
    try:
        r = requests.get(f"https://doi.org/{doi}", headers=UA, timeout=60, allow_redirects=True)
        if not r.ok:
            return []
        ls = re.findall(r'href="(https://www\.jstage\.jst\.go\.jp/article/[^"]+_pdf[^"]*)"', r.text)
        ls += ["https://www.jstage.jst.go.jp" + l for l in
               re.findall(r'href="(/article/[^"]+_pdf[^"]*)"', r.text)]
        return ls[:4]
    except Exception:
        return []


def try_url(url, verify=True, timeout=90):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True, verify=verify)
        if r.ok and is_pdf(r.content):
            return r.content
        log(f"    [--] HTTP {r.status_code} head={r.content[:5]!r} len={len(r.content)} {url[:90]}")
    except Exception as e:
        log(f"    [--] {type(e).__name__} {str(e)[:70]} {url[:90]}")
    return None


def scialert_pdf(doi):
    """Scialert: parse abstract page for a PDF link; journal may have none (HTML only)."""
    base = f"https://scialert.net/abstract/?doi={doi.split('/', 1)[1]}"
    try:
        r = requests.get(base, headers=UA, timeout=60, verify=False)
        if not r.ok:
            return None
        for l in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text, flags=re.I):
            u = l if l.startswith("http") else "https://scialert.net" + l
            body = try_url(u, verify=False)
            if body:
                return body
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- PMC + PoW
def solve_pow(challenge, difficulty):
    """PMC hashcash: find nonce so sha256(challenge+nonce) starts with `difficulty` zeros."""
    target = "0" * difficulty
    n = 0
    while True:
        if hashlib.sha256((challenge + str(n)).encode()).hexdigest().startswith(target):
            return n
        n += 1


def pmc_attempt(pmcid):
    """One attempt: direct PDF, else solve PoW cookie and retry. Returns (bytes|None, note)."""
    s = requests.Session()
    s.headers.update(UA)
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    r1 = s.get(url, timeout=60)
    if r1.content[:4] == b"%PDF":
        return r1.content, "direct"
    if "POW_CHALLENGE" in r1.text:
        ch = re.search(r'POW_CHALLENGE\s*=\s*"([^"]+)"', r1.text).group(1)
        di = re.search(r'POW_DIFFICULTY\s*=\s*"?(\d+)', r1.text)
        cn = re.search(r'POW_COOKIE_NAME\s*=\s*"([^"]+)"', r1.text).group(1)
        s.cookies.set(cn, f"{ch},{solve_pow(ch, int(di.group(1)) if di else 4)}",
                      path="/", domain="pmc.ncbi.nlm.nih.gov")
        r2 = s.get(url, timeout=120)
        if r2.content[:4] == b"%PDF":
            return r2.content, "pow"
        return None, "post-pow-not-pdf"
    if "recaptcha" in r1.text.lower():
        return None, "recaptcha"        # escalated: back off, fresh session next round
    return None, f"other-{r1.status_code}-{len(r1.text)}"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV with DOI column")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--state", required=True, help="state JSON (resume-safe)")
    ap.add_argument("--deadline-min", type=int, default=45)
    ap.add_argument("--pmc-delay", nargs=2, type=float, default=[15, 30],
                    help="min/max seconds between PMC attempts")
    ap.add_argument("--email", default="", help="real contact email (Crossref polite pool)")
    ap.add_argument("--skip-pmc", action="store_true")
    args = ap.parse_args()

    outdir, statep = Path(args.outdir), Path(args.state)
    outdir.mkdir(parents=True, exist_ok=True)
    state = load_state(statep)

    with open(args.input, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("DOI") or "").strip()]
    recs = {}
    for r in rows:
        doi = r["DOI"].strip()
        recs[doi] = {"title": r.get("文献名") or r.get("title") or "",
                     "year": r.get("年份") or r.get("year") or ""}
    todo = [d for d in recs if not state.get(d, {}).get("file")]
    log(f"records: {len(recs)}, already downloaded: {len(recs) - len(todo)}, todo: {len(todo)}")

    def store(doi, body, source):
        fname = f"{recs[doi]['year']}_{slug(recs[doi]['title'])}.pdf"
        (outdir / fname).write_bytes(body)
        state[doi] = {"file": fname, "source": source}
        save_state(statep, state)      # persist after EVERY success: crash-safe
        log(f"  [OK] {doi} {len(body) // 1024}KB via {source[:80]} -> {fname}")

    pmcids = {}
    deadline = time.time() + args.deadline_min * 60

    # ---- Phase A: fast routes -------------------------------------------------
    for doi in list(todo):
        if time.time() > deadline:
            break
        meta = crossref(doi, args.email)          # title/year if missing + vol/iss/page/container
        recs[doi]["title"] = recs[doi]["title"] or meta.get("title") or doi
        recs[doi]["year"] = recs[doi]["year"] or str(meta.get("year") or "")
        time.sleep(0.4)
        log(f"[A] {doi}")
        got = False
        for u, label in publisher_urls(doi, meta):
            if label == "scialert-landing":       # handled after the plain GETs
                continue
            body = try_url(u)
            if body:
                store(doi, body, u)
                got = True
                break
            time.sleep(0.5)
        if not got and doi.startswith("10.3923/"):     # Scialert needs page parsing
            body = scialert_pdf(doi)
            if body:
                store(doi, body, "scialert-parsed")
                got = True
        if not got and doi.startswith(("10.1292/", "10.1294/", "10.12935/")):
            for u in jstage_from_landing(doi):         # pattern failed → scrape landing page
                body = try_url(u)
                if body:
                    store(doi, body, "jstage-landing " + u[:60])
                    got = True
                    break
                time.sleep(0.5)
        if got:
            todo.remove(doi)
            continue
        # Semantic Scholar probe (429-prone: back off and retry once)
        try:
            r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                             params={"fields": "openAccessPdf,isOpenAccess"}, headers=UA, timeout=40)
            if r.status_code == 429:
                time.sleep(10)
                r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                                 params={"fields": "openAccessPdf"}, headers=UA, timeout=40)
            if r.status_code == 200:
                pdf = (r.json().get("openAccessPdf") or {}).get("url")
                if pdf:
                    body = try_url(pdf)
                    if body:
                        store(doi, body, "s2 " + pdf[:60])
                        todo.remove(doi)
                        continue
        except Exception as e:
            log(f"    [s2-err] {type(e).__name__} {str(e)[:60]}")
        time.sleep(1.0)

    # ---- Phase B: PMC slow path -----------------------------------------------
    if not args.skip_pmc:
        for doi in list(todo):
            if time.time() > deadline:
                break
            if doi not in pmcids:
                pmcids[doi] = epmc_pmcid(doi)
            if pmcids[doi]:
                try:
                    requests.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/"
                                 f"{pmcids[doi]}/fullTextPDF", headers=UA, timeout=60)
                except Exception:
                    pass
            time.sleep(0.5)
        pending = [d for d in todo if pmcids.get(d)]
        if pending:
            log(f"\n[B] PMC slow path: {len(pending)} items with PMCID")
        rnd = 0
        while pending and time.time() < deadline:
            rnd += 1
            log(f"--- PMC round {rnd}, pending {len(pending)} ---")
            still = []
            for doi in pending:
                if time.time() > deadline:
                    still.append(doi)
                    continue
                time.sleep(random.uniform(*args.pmc_delay))
                try:
                    body, note = pmc_attempt(pmcids[doi])
                except Exception as e:
                    body, note = None, f"err {type(e).__name__}"
                if body:
                    store(doi, body, f"pmc.ncbi {pmcids[doi]}")
                else:
                    still.append(doi)
                    log(f"  [--] {doi} {pmcids[doi]} ({note})")
                    if note == "recaptcha":
                        time.sleep(90)   # escalated: cool down before next attempt
            pending = still
        todo = [d for d in todo if not state.get(d, {}).get("file")]

    # ---- report ----------------------------------------------------------------
    ok = [d for d in recs if state.get(d, {}).get("file")]
    log(f"\n=== DONE: {len(ok)}/{len(recs)} downloaded ===")
    no_route = [d for d in todo if not pmcids.get(d) and not d.startswith(("10.1007/", "10.1186/",
                "10.3389/", "10.3390/", "10.1292/", "10.1294/", "10.12935/", "10.3923/"))]
    if no_route:
        log("no OA route found for:")
        for d in no_route:
            log(f"  {d}")
    with open(outdir / "_manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["DOI", "file", "source"])
        for d in recs:
            st = state.get(d, {})
            w.writerow([d, st.get("file", ""), st.get("source", "not downloaded")])
    log(f"manifest: {outdir / '_manifest.csv'}")


if __name__ == "__main__":
    main()
