# 排障手册 / Troubleshooting

本文件记录在真实网络环境（国内、代理节点、Cloudflare 拦截、PMC 风控）中实测遇到的问题及对应处理方式。
每一条都来自实际抓取失败案例，不是推测。

> 遇到失败先跑一次体检，90% 的"下不下来"能在这一步定性：
>
> ```bash
> python scripts/fetch_oa_pdfs.py --doctor --email "you@example.com"
> ```

---

## 一、症状 → 原因 → 处置（速查表）

| 症状 | 真正原因 | 处置 |
|---|---|---|
| 全部 `403`，且 Wiley / APS / Cell / Elsevier 同时中招 | 出口 IP 被 Cloudflare / Akamai 标记为机房 IP | 换出口节点（优先住宅 IP）；`--doctor` 确认；不要原地重试 |
| `403` 页面标题是 `Just a moment...` | Cloudflare **JS 托管挑战**，需要执行 JS | TLS 指纹模拟（`curl_cffi` `impersonate="chrome"`）与无头 Chrome **均无效**，只能真实浏览器手动打开 |
| `connect-err` / `SSL: UNEXPECTED_EOF_WHILE_READING` | 对端**主动掐断 TLS 握手**，不是文章没全文 | 加 `--verbose` 看异常原文；脚本已内置 3 次重试；多篇同时出现说明是网络路径问题 |
| PMC 返回约 20 KB 的 `Checking your browser - reCAPTCHA` | 请求频率触发 PMC 风控 | **停止重试**，冷却 1–2 分钟；脚本按 60s→120s→240s 退避，冷却后会恢复成可解的 PoW 页 |
| 明明有 PMCID 却只存了 `.xml` | 旧版本 XML 兜底在 Phase A 抢跑，把 DOI 从队列移除 | 已修复：XML 改为 **Phase C**，仅在 PMC 之后执行 |
| `state.json` 说已完成，但目录里没文件 | 旧版本只看 state 记录，不校验文件存在 | 已修复：自动校验文件真实存在；仍要全量重来用 `--force` |
| 文件名以 `...inflammato` 这类残词结尾 | 早期 `slugify` 按字符硬切 | 已修复：`safe_title()` 按**词边界**截断；`--filename title` 用完整标题 |
| `--verbose` 报 `unrecognized arguments` | 某次提交删掉了该参数 | 已修复（v1.2.2 起恢复），并在 v1.3.0 增强为打印 SSL 原文 |
| `oa.fcgi` 一律 404 | PMC 的 OA 包接口已下线 | 不再使用；改走 `/articles/{PMCID}/pdf/` + PoW |
| Europe PMC `fullTextPDF` 一律 404 | 该端点在 EBI 上**根本不存在**（任意 PMCID 都 404） | 已移除；PDF 只能走 PMC，EBI 仅提供 `fullTextXML` |

---

## 二、典型案例复盘

### 1. 代理开着、ChatGPT 正常，但学术站点全部 403

- 出口 IP 落在机房段（如 Datacamp / Cogent），被 Cloudflare 集中标记。
- 判定依据：**多个不相干的出版商同时 403**，且返回体都是约 5.8 KB 的挑战页。
- 注意：TUN 模式下 `curl --noproxy '*'` 与 `-x 127.0.0.1:7890` 的出口 IP **必然相同**，不能据此判断"代理没生效"。
- 处置：换节点；若目标文献有 PMC / 机构库副本，优先走仓储路线而非出版商主站。

### 2. 对 NCBI 而言，挂代理可能更差

同一台机器实测：

- 代理全开（日本节点）：`pmc.ncbi.nlm.nih.gov` TLS 握手被重置；
- 关掉代理、国内宽带直连：`200`。

NCBI 会对大量机场出口直接重置握手，**与节点速度无关**。所以 PMC 反复失败时，先试**关代理直连**，再试换节点。

### 3. PMC 第一次必断、第二次就正常

`/pdf/` 首次请求经常抛 `SSL: UNEXPECTED_EOF_WHILE_READING`，紧接着重试即可拿到文件。
因此 `attempt_pmc_download()` 内部做了 3 次递增重试——把这类抖动当"不可获取"会产生大量假阴性。

另外 `/pdf/` 会先 `301` 跳到 `/pdf/<文件名>.pdf`，跟随重定向后才能看到 PoW 挑战页。

### 4. PoW 能解，但拿不到文件不是因为解错了

PoW 求解只是拿到 `cloudpmc-viewer-pow` Cookie；真正的失败点在随后那次带 Cookie 的请求。
判据：日志里出现 `pmc-pow: difficulty=4 nonce=...` 说明 nonce 已算出，此时失败属于网络层。

### 5. bronze OA 是一种"看得见摸不着"的状态

`OpenAlex` 可能给出 `is_oa=true`，但同时 `any_repository_has_fulltext=false`。
典型代表：Cell Press 的部分文章——出版商站点免费可读，但被 Cloudflare 拦住，且**没有任何仓储副本**。
这类文献任何合法工具都拿不到，只能人工用浏览器点击下载，不要误判为工具故障。

### 6. "有 PMCID"不等于"有 PDF"

PMC 中存在 `isOpenAccess=N` 的条目：作者稿只提供**免费 HTML 阅读**，不提供 PDF 分发。
这类条目会一直失败，属于权限事实而非网络问题。

### 7. 机构知识库的 Anubis 反爬（扩展场景）

部分 DSpace 机构库（如哈勒大学）在页面层部署 Anubis：纯前端 PoW，`difficulty=3`，算法为 `sha256(randomData + nonce)`。
求解后 GET `/.within.website/x/cmd/anubis/api/pass-challenge?id=&response=&nonce=&redir=&elapsedTime=`，
拿到 `techaro.lol-anubis-auth-*` Cookie，**后续 bitstream 下载必须复用同一个 CookieJar**，否则还是挑战页。
注意：记录下常含 `Deposit-Lizenz`、`Policy` 之类的许可表 PDF，需优先选择 `/bitstream/` 正文路径并排除它们。

---

## 三、推荐操作顺序

1. `--doctor` 判定是网络问题还是权限问题；
2. 网络问题 → 换节点 / 关代理直连 / 加大 `--pmc-delay`；
3. 权限问题 → 直接告诉用户「无合法 OA 副本」，不要反复重试；
4. 需要在报告里说明来源时，读 `_manifest.csv` 的 `Source` 与 `Status` 两列。
