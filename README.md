# oa-pdf-download

A [ZCode](https://zcode.com) skill: batch-download **legally open-access** PDF full
texts for a list of papers (DOI list / literature Excel / CSV), then honestly report
which papers cannot be obtained and why. Every route in it was field-tested in an
October 2026 run (51/74 veterinary-coronavirus papers fetched in one session).

## What it does

Two-phase pipeline over a DOI list:

- **Phase A (fast)** — publisher direct URL patterns (Springer / BMC / SpringerOpen /
  Frontiers / MDPI / J-Stage / Scialert), Europe PMC fullTextPDF, and a Semantic
  Scholar `openAccessPdf` probe. All URLs built from Crossref metadata.
- **Phase B (slow, anti-bot aware)** — PMC PDFs via
  [pmc.ncbi.nlm.nih.gov](https://pmc.ncbi.nlm.nih.gov), including the hashcash
  **proof-of-work** interstitial solver (sha256 nonce → `cloudpmc-viewer-pow`
  cookie), fresh session per attempt, 15–30 s randomized pacing, multi-round
  retries, and 90 s+ cooldown on reCAPTCHA escalation.

Crash-safe: a state JSON maps DOI → {file, source} and is persisted after every
success, so the run can be killed and relaunched. Output PDFs are validated
(`%PDF` magic, >15 KB) and named `{year}_{title-slug}.pdf`.

**Hard rule: legal OA channels only.** No paywall circumvention, no Sci-Hub. Papers
that are paywalled with no OA copy are reported as such so you can reach them via
campus/institutional access.

## Install

Copy (or clone) this folder into a skill discovery directory:

```
<project>/.zcode/skills/oa-pdf-download/     # project scope
~/.agents/skills/oa-pdf-download/            # user scope (all projects)
```

i.e. the directory must contain `SKILL.md` and `scripts/fetch_oa_pdfs.py`.

## Usage

Then just ask your agent, e.g. 「把这些文献能下载的OA全文都下载下来」 / "download the
OA full texts for these papers". For direct script use:

```bash
python scripts/fetch_oa_pdfs.py \
    --input records.csv \        # CSV with a DOI column; 文献名/年份 columns optional
    --outdir  PDFs \
    --state   state.json \       # resume-safe progress
    --email   you@university.edu.cn \   # real address → Crossref polite pool
    --deadline-min 45
```

The skill's `SKILL.md` additionally documents the verified URL patterns per
publisher, the PMC PoW exchange, reCAPTCHA countermeasures, and China-network
workarounds (DNS-poisoned `www.ncbi.nlm.nih.gov` → use `pmc.ncbi.nlm.nih.gov` and
Europe PMC; Cloudflare-403 hosts; Unpaywall email quirks).

## Requirements

Python 3.10+, `requests`. No API keys needed (all endpoints are open).
