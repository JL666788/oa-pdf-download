---
name: oa-pdf-download
description: >-
  Batch-download legally open-access PDF full texts for a list of papers (DOI list or
  literature Excel/CSV). Use whenever the user asks to 下载全文 / 下载PDF / 获取原文 /
  下载文献 / "which of these papers can I get as PDF" / batch fetch OA fulltexts — even
  mid-workflow after a literature search or Excel deliverable. Encodes field-tested
  routes: PMC proof-of-work solving, Springer/BMC/Frontiers/MDPI/J-Stage direct URL
  patterns, Semantic Scholar probe, reCAPTCHA-aware pacing, and China-network
  workarounds (www.ncbi.nlm.nih.gov DNS pollution, Cloudflare 403 hosts).
---

# OA PDF Download

Download the legally open-access PDF full texts for a set of papers, honestly report
which cannot be obtained and why. Every technique here was verified working in
October 2026 (51/74 ECoV papers downloaded in one run).

## Hard rule

**Legal open-access channels only** — PMC/Europe PMC, publisher OA endpoints,
repository copies surfaced by Semantic Scholar. No paywall circumvention, no
Sci-Hub, no forged cookies beyond what PMC itself issues to every browser
(the proof-of-work cookie in step 5 is an anti-scraping toll, not an access
control: solving it is exactly what a browser does). If a paper is paywalled
with no OA copy, say so in the report — the user can reach it via campus access.

## Quick start

Use the bundled script for any list of ≥3 DOIs; do not reinvent the pipeline:

```bash
python "<skill-dir>/scripts/fetch_oa_pdfs.py" \
    --input records.csv --outdir PDFs --state state.json \
    --email user@real-university.edu.cn --deadline-min 45
```

- Input CSV: column `DOI` required; `文献名`/`title` and `年份`/`year` optional
  (used for `{year}_{title-slug}.pdf` filenames; else fetched from Crossref).
- State JSON: maps DOI → `{file, source}`. Re-running skips finished items —
  the script is crash-safe and designed to be relaunched after failures.
- Output: PDFs + `_manifest.csv` (DOI/file/source per record) + console report
  listing items with no OA route.

## Pipeline: two phases, deliberately paced

**Phase A (fast, ~0.5–1 s between requests)** — try each DOI against:

1. Publisher direct URL patterns (table below), built from Crossref metadata
   (`api.crossref.org/works/{doi}` gives volume/issue/page/container-title).
2. Springer universal fallback: `https://link.springer.com/content/pdf/{doi}.pdf`
   — works for 10.1007 journals *and* book chapters *and* 10.1186 BMC/SpringerOpen.
3. Europe PMC fullTextPDF: `https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextPDF`.
4. Semantic Scholar probe: `api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf`
   (429 → sleep 10 s, retry once; it rate-limits aggressively).

**Phase B (slow, 15–30 s between requests, multi-round until a ~45 min deadline)**
— for every DOI with a PMCID, download from PMC. This route yielded 39/51 PDFs in
the reference run, including Elsevier papers that are only OA via PMC deposits
(e.g. COVID-19 resource centre, author manuscripts).

Why this order: Phase A fails fast and cheap; Phase B is slow and probabilistic
under anti-bot escalation, so it runs last, in rounds, with state saved to disk
after every single success.

## PMC proof-of-work (the key technique)

`https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/pdf/` usually returns an
interstitial, not the PDF. It embeds a hashcash challenge:

```python
def pmc_attempt(pmcid):
    s = requests.Session(); s.headers.update(UA)
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    r1 = s.get(url, timeout=60)
    if r1.content[:4] == b"%PDF":
        return r1.content, "direct"
    if "POW_CHALLENGE" in r1.text:
        ch = re.search(r'POW_CHALLENGE\s*=\s*"([^"]+)"', r1.text).group(1)
        di = re.search(r'POW_DIFFICULTY\s*=\s*"?(\d+)', r1.text)
        cn = re.search(r'POW_COOKIE_NAME\s*=\s*"([^"]+)"', r1.text).group(1)
        nonce = solve_pow(ch, int(di.group(1)) if di else 4)   # sha256(ch+str(n)) starts with "0"*diff
        s.cookies.set(cn, f"{ch},{nonce}", path="/", domain="pmc.ncbi.nlm.nih.gov")
        r2 = s.get(url, timeout=120)
        if r2.content[:4] == b"%PDF":
            return r2.content, "pow"
        return None, "post-pow-not-pdf"
    if "recaptcha" in r1.text.lower():
        return None, "recaptcha"          # escalated — back off, fresh session next round
    return None, f"other-{r1.status_code}-{len(r1.text)}"
```

Difficulty has been 4 (≈ a few seconds of pure-Python hashing). The cookie value
is `f"{challenge},{nonce}"`. Always verify the response is a PDF, not another
interstitial.

## Anti-bot discipline (reCAPTCHA escalation)

Rapid sequential PMC downloads trigger a Google reCAPTCHA page (~20 KB HTML, no
`POW_` constants, contains `recaptcha`). Once escalated, **even solved PoW cookies
fail**; per-attempt success drops to ~30–50% and recovers only with patience:

- **Fresh `requests.Session` per attempt** — never reuse a session that saw a challenge.
- **15–30 s randomized sleep between attempts**; on a reCAPTCHA page, cool down 90 s+.
- **Multi-round retry loop** over the pending list until a deadline; a given item
  typically succeeds within a few rounds. The reference run cleared 23/23 in 14 rounds.
- Run long retry loops as a **background script** (`run_in_background`), `print(..., flush=True)`,
  and persist state after every success so a kill loses nothing.

## Publisher URL patterns (verified)

| Publisher | DOI prefix | URL pattern |
|---|---|---|
| Springer (journals + book chapters) | 10.1007 | `https://link.springer.com/content/pdf/{doi}.pdf` |
| BMC / SpringerOpen | 10.1186 | `https://{journal}.biomedcentral.com/counter/pdf/{doi}.pdf`; same DOI also via link.springer.com |
| Frontiers | 10.3389 | `https://www.frontiersin.org/journals/{journal}/articles/{doi}/pdf` and `/articles/{doi}/pdf` |
| MDPI | 10.3390 | DOI id = `{abbrev}{vol2}{issue2}{art4}` → `https://www.mdpi.com/{issn}/{vol}/{issue}/{art}/pdf` (Cloudflare may 403 — fall through to PMC) |
| J-Stage (JVMS/JES/JVMA) | 10.1292, 10.1294, 10.12935 | `https://www.jstage.jst.go.jp/article/{j}/{vol}/{iss}/{vol}_{firstpage}/_pdf/-char/en`; if that 404s, follow the `doi.org` redirect and scrape the `_pdf` href from the landing page |
| Scialert | 10.3923 | Parse `https://scialert.net/abstract/?doi={id}` for a PDF link — many articles are HTML-only and have **no PDF at all** |

Not routable (report as paywalled unless a PMCID exists): Elsevier 10.1016,
Wiley 10.1111 (`.../pdfdirect` returns 403), Sage 10.1177, AJVR 10.2460,
Vet Record 10.1136, Thieme 10.1055, Hindawi (Cloudflare 403 on all endpoints).

## Environment quirks (China network, verified 2026-10)

- `www.ncbi.nlm.nih.gov` is DNS-poisoned (returns an unrelated page). Use
  `pmc.ncbi.nlm.nih.gov` for PDFs and Europe PMC (`www.ebi.ac.uk/europepmc`) for
  PMCID lookup — both work. NCBI E-utilities (`eutils.ncbi.nlm.nih.gov`) works.
- `sciencedirect.com` and `journals.sagepub.com`: connection timeouts/SSL failures.
- `mdpi.com`, `wiley.com`, `hindawi.com`: Cloudflare 403 to datacenter-ish clients.
- Unpaywall API rejects placeholder emails (422) — use a real address or skip it.
- Semantic Scholar: 429 on anything but a slow crawl.
- `duckduckgo`/`bing` searches time out — don't build the pipeline around them.

## Validation and reporting

- Accept a body as PDF only if it starts with `%PDF` and is >15 KB. Never save
  an HTML interstitial as `.pdf`, and never trust `Content-Type` alone.
- Validate file size plausibility for the item (a 12 KB "PDF" is usually an error page).
- Final report: N/M downloaded, per-item source route, and for each failure an
  honest reason — `paywalled (no OA copy)`, `no PDF exists (HTML-only journal)`,
  `network-blocked host`, `no PMCID`. Never pad the report with unverified guesses.
- Name files `{year}_{title-slug}.pdf` so they sort chronologically and match the
  literature table's 题名 column for later cross-checking.
