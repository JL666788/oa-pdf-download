---
name: oa-pdf-download
version: 1.2.0
author: JL666788
description: >-
  Batch-download legally open-access (OA) academic full-text PDFs from a DOI list
  or literature Excel/CSV, then honestly report unobtained papers and reasons.
  Triggers on requests like: 下载全文 / 下载PDF / 获取原文 / 下载文献 / "download OA full texts" /
  batch fetch papers. Features built-in PMC Hashcash proof-of-work solver, Springer/
  Frontiers/MDPI/J-Stage direct pattern routing, Semantic Scholar probing, anti-bot
  pacing, and China network DNS-pollution mitigations.
tags:
  - academic-research
  - literature
  - pdf-download
  - open-access
  - crossref
  - pubmed-pmc
---

# 📚 OA PDF Download: Academic Harvester Skill

Automate the batch acquisition of **legally open-access** academic PDF full texts for a given list of research papers, ensuring 100% legal compliance, resilient anti-scraping countermeasures, and transparent reporting.

Field-tested and verified in October 2026 (51/74 veterinary-coronavirus papers fetched in a single session).

---

## ⚖️ Golden Rule & Ethical Boundary

> [!IMPORTANT]
> **Strict Legal Open-Access Only**:
> - Only fetch from legitimate OA channels (Publisher OA portals, PubMed Central, Europe PMC, institutional open repositories via Semantic Scholar).
> - **Never attempt paywall circumvention, never query Sci-Hub, and never use unauthorized cookies.**
> - The PMC Proof-of-Work cookie solved in Phase B is an anti-scraping rate-limiting challenge, not an access control wall (it mirrors standard browser execution).
> - If a paper is purely paywalled with no legal OA copy, **report it transparently** so the user can acquire it via university/institutional library access.

---

## 🎯 When to Activate This Skill

Activate this skill whenever the user asks to:
- 下载全文 / 下载文献 / 下载PDF / 获取论文原文 / 批量下载论文
- "Download the PDFs for these papers" / "Fetch all available full texts"
- "Which of these papers are open access?"
- Mid-workflow handoff after a literature search or systematic review CSV deliverable.

---

## 🛠️ Standard Operating Procedure (SOP)

When assigned to fetch PDFs, do **not** write a custom ad-hoc downloader from scratch. Execute the battle-tested bundled script:

### Step 1: Normalize Input
Check user input. It may be:
- A CSV or Excel file containing a `DOI` column (optional `文献名`/`title`, `年份`/`year` columns).
- A raw list of DOIs in text format.
*(If given an Excel file `.xlsx`, convert it to `.csv` or pass the DOIs).*

### Step 2: Background Script Execution
Since downloading dozens of papers with PMC anti-bot pacing can take 10–40 minutes, **always run the script as a background process** (`run_command` with async / background support):

```bash
python "<skill-dir>/scripts/fetch_oa_pdfs.py" \
    --input "records.csv" \
    --outdir "PDFs" \
    --state "state.json" \
    --email "researcher@real-university.edu.cn" \
    --deadline-min 45
```

- **`--state state.json`**: Transactional state persistence. The script saves progress after **every single successful download**. If interrupted, relaunching immediately resumes without repeating finished items.
- **`--email <email>`**: Provides access to Crossref's polite pool for faster, higher-rate metadata resolution.

### Step 3: Monitor & Defend Against Rate Limits
- Periodically verify background task output.
- The pipeline automatically navigates two phases:
  1. **Phase A (Fast, ~0.5–1s)**: Publisher direct patterns + Europe PMC + Semantic Scholar probe.
  2. **Phase B (Paced, 15–30s)**: Multi-round PMC downloads with Hashcash PoW solving and 90s+ reCAPTCHA cooldowns.

### Step 4: Deliver Structured Academic Report
Once complete, read `PDFs/_manifest.csv` and present a structured summary to the user using the template below.

---

## 📊 User Delivery Report Template

```markdown
### 📥 文献全文（OA）下载完成汇报

- **总文献数量**：N 篇
- **成功获取全文**：M 篇（占比 XX%）
- **无法直接获取**：K 篇（主要为商业付费出版物）
- **输出文件目录**：`PDFs/`
- **详细对照清单**：`PDFs/_manifest.csv`

#### 📦 获取渠道分布
| 渠道来源 | 数量 | 说明 |
|---|---|---|
| PMC (Hashcash PoW) | X 篇 | 通过 PubMed Central 机构存证与合规解密获取 |
| Springer / BMC | X 篇 | 开放出版商直链直连 |
| Frontiers / MDPI | X 篇 | OA 开放期刊官方端点 |
| Semantic Scholar | X 篇 | 知识库仓储公开副本 |

#### ⚠️ 未获取文献诊断与获取建议
对于未能获取合法 OA 全文的文献，已核实原因如下：
1. **商业数据库付费墙（无公开 OA 存证）**：
   - `[DOI]` 《论文标题》 (Elsevier / Wiley / Sage) ➔ *建议：请通过高校校园网 WebVPN 或图书馆数据库直接下载*
2. **出版商无 PDF 全文（仅 HTML 格式）**：
   - `[DOI]` 《论文标题》 (Scialert 等平台)
```

---

## 🔬 Core Engineering & Verification Reference

### 1. PMC Proof-of-Work (Hashcash Challenge)
`https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/pdf/` frequently presents an interstitial HTML challenge containing:
- `POW_CHALLENGE`: Random alphanumeric token.
- `POW_DIFFICULTY`: Required leading zeros in hex SHA-256 hash (typically 4).
- `POW_COOKIE_NAME`: Usually `cloudpmc-viewer-pow`.

**Solver implementation snippet**:
```python
def solve_pow(challenge: str, difficulty: int = 4) -> int:
    target = "0" * difficulty
    nonce = 0
    ch_bytes = challenge.encode()
    while True:
        if hashlib.sha256(ch_bytes + str(nonce).encode()).hexdigest().startswith(target):
            return nonce
        nonce += 1
```
Set cookie as `f"{challenge},{nonce}"` and reissue request with a **fresh session**.

### 2. Anti-Bot Discipline (reCAPTCHA Mitigation)
Rapid sequential downloads trigger Google reCAPTCHA (~20KB HTML without POW constants):
- **Fresh `requests.Session` per attempt**: Never reuse a tainted session.
- **15–30s randomized delay**: Mimics human reading and browser behavior.
- **90s+ cooldown on reCAPTCHA**: Allow server-side suspicion counters to reset.

### 3. Verified Publisher URL Patterns

| Publisher | DOI Prefix | Deterministic URL Format |
|---|---|---|
| **Springer** | `10.1007/` | `https://link.springer.com/content/pdf/{doi}.pdf` |
| **BMC / SpringerOpen** | `10.1186/` | `https://{journal}.biomedcentral.com/counter/pdf/{doi}.pdf` |
| **Frontiers** | `10.3389/` | `https://www.frontiersin.org/articles/{doi}/pdf` |
| **MDPI** | `10.3390/` | `https://www.mdpi.com/{issn}/{vol}/{iss}/{art}/pdf` (Parsed from DOI) |
| **J-Stage** | `10.1292/`, `10.1294/` | `https://www.jstage.jst.go.jp/article/{j}/{vol}/{iss}/{vol}_{page}/_pdf/-char/en` |
| **Scialert** | `10.3923/` | Parse abstract page `https://scialert.net/abstract/?doi={id}` |

### 4. China Mainland Network Specifics (Verified 2026-10)
- `www.ncbi.nlm.nih.gov` suffers from DNS pollution in several mainland regions. Always route via `pmc.ncbi.nlm.nih.gov` for PDFs and Europe PMC (`www.ebi.ac.uk/europepmc`) for PMCID lookup.
- `sciencedirect.com` and `journals.sagepub.com` frequently drop connections/reset SSL.
- Unpaywall API strictly rejects placeholder emails (returns 422). Use a valid email or rely on Europe PMC / Semantic Scholar.
