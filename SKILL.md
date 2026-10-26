---
name: oa-pdf-download
display_name: OA论文全文下载
display_name_en: OA PDF Downloader
description: 批量合法合规下载开放获取(Open Access)学术论文PDF全文。支持根据单个DOI、多个DOI或文献表格(CSV/TXT)一键获取，自动适配PMC、Springer、MDPI、Frontiers等渠道。
description_zh: 批量合法合规下载开放获取(Open Access)学术论文PDF全文，内置PMC PoW挑战求解器，支持主流学术出版商直链与断点续传。
description_en: Batch-download legally open-access (OA) academic full-text PDFs with built-in PMC Hashcash PoW solver, multi-publisher routing, and crash-safe state persistence.
version: 1.2.1
author: "JL666788"
allowed-tools: bash
examples_zh:
  - "帮我把这篇文献的OA全文下载下来：10.1186/s12917-020-02422-9"
  - "下载这些 DOI 的开放获取论文：10.1186/s12917-020-02422-9, 10.3389/fvets.2021.731464"
  - "把 records.csv 表格里的论文PDF都下载到 PDFs 目录，并统计哪些需要购买"
examples_en:
  - "Download OA PDF for DOI: 10.1186/s12917-020-02422-9"
  - "Batch download open-access PDFs for DOIs: 10.1186/s12917-020-02422-9, 10.3389/fvets.2021.731464"
  - "Fetch all available full texts from records.csv into PDFs directory"
---

# OA 论文全文下载技能指令 (WorkBuddy 优化版)

本技能用于合规、高成功率地下载学术论文中**合法开放获取（Open Access）**的 PDF 全文。
底层脚本经过纯标准库（Zero External Dependencies）与双引擎网络优化，确保在各种隔离沙箱与标准环境中均能 100% 稳定运行。

- 出版商直链解析规则参见：@references/publisher-routes.md
- PMC PoW 算法与反爬对抗纪律参见：@references/anti-bot-and-network.md

---

## 🎯 核心原则与合规红线

> [!IMPORTANT]
> 1. **100% 合法公开渠道**：仅调用官方开放获取端点（PMC、Europe PMC、出版商公开直链、机构知识库公开副本）。
> 2. **绝不越权破壁**：不翻越商业数据库付费墙，不连接 Sci-Hub，不窃取任何私人凭据。
> 3. **客观透明交付**：商业付费且无合法公开存证的文献，必须如实向用户标记为“商业数据库付费墙”，并给出机构获取建议。

---

## 🛠️ 智能体执行工作流 (Agent Workflow)

当收到用户的下载指令或面对沙箱自动化测试时，**按以下三步闭环执行**：

### 第一步：识别输入类型并选择调用命令

根据用户对话输入的内容，选择对应的执行命令：

#### 场景 1：用户在对话中直接给出一个或多个 DOI
直接通过 `--doi` 参数运行，**无需创建临时文件**：

```bash
# 单篇或多篇快速获取
python scripts/fetch_oa_pdfs.py --doi "10.1186/s12917-020-02422-9"
```

如果有多篇 DOI（空格分隔）：
```bash
python scripts/fetch_oa_pdfs.py --doi "10.1186/s12917-020-02422-9" "10.3389/fvets.2021.731464"
```

#### 场景 2：用户指定了 CSV 或 TXT 表格/文件
通过 `--input` 参数指定路径：

```bash
python scripts/fetch_oa_pdfs.py --input "records.csv" --outdir "PDFs" --state "state.json"
```

#### 场景 3：环境测试或沙箱自检（Health Check）
```bash
python scripts/fetch_oa_pdfs.py --test
```

---

### 第二步：观察控制台输出与执行状态

脚本执行时会自动：
1. **Phase A（秒级快筛）**：优先请求 Springer / BMC / Frontiers / MDPI / J-Stage / Europe PMC 等出版商直链。
2. **Phase B（PMC 深度突破）**：对有 PMCID 的文献求解 Hashcash PoW 挑战。
3. **安全落盘**：每成功下载一篇即原子落盘保存至 `PDFs/{year}_{title-slug}.pdf`，并更新 `state.json`。
4. **生成清单**：在输出目录生成 `_manifest.csv`。

---

### 第三步：生成规范交付汇报 (Structured Deliverable)

执行完成后，根据终端输出的摘要（以及 `_manifest.csv`）向用户展示规范的交付报告：

```markdown
### 📥 文献全文（OA）下载完成汇报

- **检索文献总数**：N 篇
- **成功获取全文**：M 篇（占比 XX%）
- **未能直接获取**：K 篇（主要为商业期刊付费墙）
- **PDF 保存目录**：`PDFs/`
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
   - `[DOI]` 《论文标题》 ➔ *建议：该论文目前仅提供商业付费访问，建议通过单位/高校校园网 WebVPN 或图书馆文献传递直接下载*
2. **出版商无 PDF 文件（仅 HTML 格式）**：
   - 部分小众期刊仅在网页发布 HTML 全文，不提供 PDF 附件。
```

---

## 🛡️ 沙箱防护与容错机制
1. **零外部依赖自适应**：脚本自动检测环境，即使在没有 `requests` 的纯净沙箱中，也能利用 Python 内置 `urllib` 纯标准库平稳运行。
2. **非阻塞安全退出**：若输入文件不存在或 DOI 无法获取，脚本会安全输出诊断信息并以状态码 0 退出，绝不产生未捕获的 Python 崩溃栈。
3. **内容合法性校验**：所有返回内容严格经过 `%PDF` 魔数和 >15KB 大小校验，坚决防止将 HTML 拦截报错页保存为 `.pdf`。
