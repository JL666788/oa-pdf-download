---
name: oa-pdf-download
display_name: OA论文全文下载
display_name_en: OA PDF Downloader
description: 批量合法下载开放获取(Open Access)学术论文PDF全文。当用户需要下载文献、下载论文、下载全文、下载PDF、获取原文、批量下载PDF或查询论文是否有公开OA版本时触发。
description_zh: 批量合法下载开放获取(Open Access)学术论文PDF全文，内置PMC PoW挑战求解器，支持主流学术出版商直链与断点续传。
description_en: Batch-download legally open-access (OA) academic full-text PDFs with built-in PMC Hashcash PoW solver and anti-bot pacing.
version: 1.0.0
author: "JL666788"
allowed-tools: bash
examples_zh:
  - "帮我把这篇文献的OA全文下载下来：10.1186/s12917-020-02422-9"
  - "把 records.csv 表格里的论文PDF都下载到 PDFs 目录，并统计哪些需要购买"
  - "下载这些 DOI 的开放获取论文并生成 manifest 清单"
examples_en:
  - "Download OA PDF for DOI: 10.1186/s12917-020-02422-9"
  - "Batch download open-access PDFs from records.csv into PDFs directory"
  - "Fetch all available full texts for this DOI list and output manifest"
---

# OA 论文全文下载技能指令

本技能用于合规、批量下载学术论文中**合法开放获取（Open Access）**的 PDF 全文。每一条技术路线均经过真实科研环境实测验证，在保证 100% 版权合规的前提下，最大化全文获取成功率。

相关详细参考规范：
- 出版商直链解析规则参见：@references/publisher-routes.md
- PMC PoW 算法与反爬对抗纪律参见：@references/anti-bot-and-network.md

---

## 核心执行原则与合规红线

> [!IMPORTANT]
> 1. **仅限合法 OA 渠道**：仅调用官方开放获取端点（PMC、Europe PMC、出版商公开直链、机构知识库公开副本）。
> 2. **绝不越权**：不绕过付费墙，不连接 Sci-Hub，不伪造任何未授权账号凭据。
> 3. **真实客观报告**：商业付费且无公开存证的文献，必须如实向用户标记为“商业数据库付费墙”，方便用户通过高校图书馆或校园网 WebVPN 获取。

---

## 执行步骤与操作指引

当用户要求下载论文或提供 DOI 列表时，按以下标准化流程执行：

### 1. 规范化输入数据
- 检查用户提供的输入文件（支持 CSV 或 TXT）。
- 若为 CSV，需包含 `DOI` 列，可选包含 `文献名`（或 `title`）、`年份`（或 `year`）列用于生成清晰规范的文件名。
- 若为纯文本，每行一个 DOI 即可。

### 2. 调度执行脚本
通过 Bash 工具在后台调度执行随包脚本 `scripts/fetch_oa_pdfs.py`，避免阻塞主会话：

```bash
python scripts/fetch_oa_pdfs.py \
    --input "records.csv" \
    --outdir "PDFs" \
    --state "state.json" \
    --email "researcher@real-university.edu.cn" \
    --deadline-min 45
```

- **`--state state.json`**：事务级断点保护，每下载成功一篇立即写入磁盘。即便脚本被中断或超时终止，重新启动亦可无缝跳过已完成项。
- **`--email`**：传入真实邮箱可进入 Crossref API 的 "Polite Pool"，获取更快更稳定的元数据响应。

### 3. 两阶段下载调度机制
脚本内部自动流转执行两阶段管道：
- **Phase A (快筛阶段)**：秒级扫描 Springer、BMC、Frontiers、MDPI、J-Stage 直链及 Semantic Scholar 预印本源。
- **Phase B (精细阶段)**：针对具备 PMCID 的文献，启动带 Hashcash PoW 碰撞求解器的 PMC 下载，配合 15~30s 随机步频与 90s+ reCAPTCHA 冷却防范。

### 4. 交付成果与汇报

下载完成后，读取生成的 `PDFs/_manifest.csv`，并按照以下格式向用户汇报：

```markdown
### 📥 文献全文（OA）下载完成汇报

- **总检索文献**：N 篇
- **成功获取全文**：M 篇（占比 XX%）
- **未能直接获取**：K 篇（主要为商业期刊付费墙）
- **输出文件目录**：`PDFs/`
- **详细对照清单**：`PDFs/_manifest.csv`

#### 📦 获取渠道分布
| 渠道来源 | 数量 | 说明 |
|---|---|---|
| PMC (PoW 求解) | X 篇 | 通过 PubMed Central 机构存证与合规解密获取 |
| Springer / BMC | X 篇 | 开放出版商直连 |
| Frontiers / MDPI | X 篇 | 官方开源期刊端点 |
| Semantic Scholar | X 篇 | 机构仓储公开副本 |

#### ⚠️ 未获取文献诊断与建议
1. **商业数据库付费墙（无公开 OA 存证）**：
   - `[DOI]` 《论文标题》 ➔ *建议：请通过单位/高校校园网 WebVPN 或图书馆馆际互借直接下载*
2. **出版商无 PDF 文件（仅 HTML 格式）**：
   - 部分小众期刊仅在网页发布 HTML 全文，不提供 PDF 附件。
```

---

## 容错与异常处理
1. **网络超时**：Phase A 请求若超时会自动跳过进入 Phase B 或下一项，不卡死流程。
2. **文件真伪校验**：所有返回内容严格经过 `%PDF` 魔数和 >15KB 大小校验，坚决防止将 HTML 拦截报错页保存为 `.pdf`。
