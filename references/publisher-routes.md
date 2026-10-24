# 出版商直接下载路由与规则对照表

本文档记录了经过验证的合法开放获取 (Open Access) 出版商直接 PDF 端点规则。

## 1. 验证可用的出版商直接路由

| 出版社 / 平台 | 典型 DOI 前缀 | URL 格式规则 / 解析方式 | 说明 |
|---|---|---|---|
| **Springer** (期刊与图书章节) | `10.1007/` | `https://link.springer.com/content/pdf/{doi}.pdf` | 覆盖 10.1007 全部开放获取文章及图书 |
| **BMC / SpringerOpen** | `10.1186/` | `https://{journal}.biomedcentral.com/counter/pdf/{doi}.pdf` | 同一 DOI 也可通过 link.springer.com 获取 |
| **Frontiers** | `10.3389/` | `https://www.frontiersin.org/articles/{doi}/pdf` 或 `/journals/*/articles/{doi}/pdf` | 官方文章直链 |
| **MDPI** | `10.3390/` | `https://www.mdpi.com/{issn}/{vol}/{issue}/{art}/pdf` | 通过 DOI 后缀解析卷、期、文章编号并映射标准 ISSN |
| **J-Stage** | `10.1292/`, `10.1294/`, `10.12935/` | `https://www.jstage.jst.go.jp/article/{j}/{vol}/{iss}/{vol}_{page}/_pdf/-char/en` | 若 404 则请求 `doi.org/{doi}` 并解析落地页中的 `_pdf` 链接 |
| **Europe PMC** | 具有 PMCID 的论文 | `https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextPDF` | EBI Europe PMC 官方开放接口 |
| **Semantic Scholar** | 任意 DOI | `https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf` | 探测机构知识库与公开预印本链接 |
| **Scialert** | `10.3923/` | 解析落地页 `https://scialert.net/abstract/?doi={id}` 提取 PDF 链接 | 许多文章仅有 HTML 格式，无 PDF 文件 |

## 2. 无法直接路由的商业付费期刊（如无公开存证则如实报告）
- Elsevier (`10.1016/`)：商业订阅，除非作者已在 PMC 存入公开手稿。
- Wiley (`10.1111/`)：`pdfdirect` 接口返回 403。
- Sage (`10.1177/`)、AJVR (`10.2460/`)、Thieme (`10.1055/`)、Hindawi（Cloudflare 403 阻断）。
- **处理原则**：坚守合法底线，如实汇报为付费文献，建议用户通过高校图书馆或校园网 WebVPN 获取。
