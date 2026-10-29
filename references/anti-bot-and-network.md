# 反爬虫对抗与国内网络环境参考指南

## 1. NCBI PMC Proof-of-Work (Hashcash PoW) 挑战机制
`https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/pdf/` 通常返回拦截页面，内嵌 Hashcash 挑战：
- `POW_CHALLENGE`: 随机字符串 nonce。
- `POW_DIFFICULTY`: 目标哈希前缀零的个数（通常为 4）。
- `POW_COOKIE_NAME`: 存储结果的 Cookie 键名（如 `cloudpmc-viewer-pow`）。
- **求解逻辑**：寻找整数 `n`，使得 `sha256(challenge + str(n))` 的十六进制表示以 `0000` 开头。
- **验证通行证**：设置 Cookie 为 `f"{challenge},{nonce}"` 并重发请求。每次尝试需使用独立的 `requests.Session`。

## 2. reCAPTCHA 升级防范纪律
若短时间内高频请求 PMC，会被升级为 Google reCAPTCHA 拦截（HTML 大小约 20KB）：
- 此时即使携带 PoW Cookie 也会失败。
- **应对纪律**：每次尝试之间必须保持 15~30s 随机间隔；一旦检测到 `recaptcha`，必须冷却等待 90 秒以上再发起重试。

## 3. 国内科研网络适配注意事项（Verified 2026-10）
- `www.ncbi.nlm.nih.gov` 存在区域性 DNS 污染，必须采用 `pmc.ncbi.nlm.nih.gov` 下载 PDF，并采用欧洲生物信息研究所 Europe PMC (`www.ebi.ac.uk/europepmc`) 查询 PMCID。
- Unpaywall API 严禁使用占位邮箱（返回 422 错误），需传入真实邮箱或采用 Europe PMC / Semantic Scholar 替代。
- Semantic Scholar API 请求过于密集会触发 429 限流，需退避 8~10 秒后单次重试。

## 4. 实测补充（2026-10，多次复现）
- **`/pdf/` 会先 301 跳转**到 `/pdf/<文件名>.pdf`，跟随重定向后才看到 PoW 页。只请求一次且不跟随会误判为异常。
- **`SSL: UNEXPECTED_EOF_WHILE_READING` 多为瞬时抖动**：同一 PMCID 首次必断、第二次成功。脚本内置 3 次递增重试；把它当作"不可获取"会产生大量假阴性。
- **reCAPTCHA 是临时状态**：冷却 1–2 分钟后 `/pdf/` 会恢复成可解的 PoW 挑战页。连续重试只会延长封锁，脚本按 60s→120s→240s 逐轮退避。
- **对 NCBI 而言代理可能更差**：同一台机器实测「代理全开时 TLS 握手被重置，关代理直连反而 200」。NCBI 会重置大量机场出口的握手，先用 `--doctor` 区分再换节点。
- **TLS 指纹模拟过不了 Cloudflare JS 挑战**：`curl_cffi impersonate="chrome"` 与无头 Chrome 对 `Just a moment...` 页面均无效，此类站点只能真实浏览器人工点击。
- **Europe PMC 的 `{PMCID}/fullTextPDF` 端点不存在**（任意 PMCID 均 404），EBI 只提供 `fullTextXML`；不要把 XML 当 PDF 存。
- **PMC 的 `oa.fcgi` OA 包接口已下线**，全部返回 404 诊断页。
