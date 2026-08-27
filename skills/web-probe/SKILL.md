---
name: web-probe
version: 1.0.0
description: "前端自动化验证：用本机 Chrome 打开指定 URL，并按需截图、抓网络请求（HAR/JSON）、收集 console 日志。各能力为独立开关，可原子使用或任意组合（如「打开 URL 然后抓包」）。当用户要对某个网页做可视化验收、截图、抓包/看请求、排查前端报错、或验证本地开发服务（localhost）时使用。不负责：无浏览器的纯 HTTP 抓取（用 web_fetch）、后端接口压测、E2E 断言编写。"
metadata:
  requires:
    bins: [node]
---

# web-probe —— 前端自动化验证

用 Playwright 驱动本机 Chrome，对网页做「打开 / 截图 / 抓包 / 收 console」。每个产物是独立开关，可原子使用，也可任意组合。

工具位置：`~/.kiro/skills/web-probe/web-probe.mjs`

## 适用范围

| 适用 ✅ | 不适用 ❌ |
|---------|-----------|
| 打开 URL 渲染截图（含整页） | 无需浏览器的纯文本抓取 → `web_fetch` |
| 抓包：录 HAR / 导出请求列表 | 后端接口压测 / 批量请求 |
| 收集 console 日志与页面报错 | 编写持久化 E2E 测试用例 |
| 验证本地开发服务（localhost/https 自签名） | 需真实 OS「默认浏览器」品牌（只能驱动 Chrome/Edge/Chromium） |
| 登录态抓包（传 cookie / header） | |

## 前置检测（每次使用前）

1. 确认依赖已装：`~/.kiro/skills/web-probe/node_modules/playwright-core` 存在；
   若不存在，在该目录执行 `npm install`。
2. 默认用系统 Chrome（`--channel chrome`）。若本机无 Chrome，脚本会自动回退到 Playwright 自带 chromium；
   若两者都无，提示用户安装 Chrome 或执行 `npx playwright install chromium`。

## 命令

```
node ~/.kiro/skills/web-probe/web-probe.mjs capture <url> [flags]
```

stdout 始终返回一段 JSON 摘要：`title` / `status` / 请求总数 / 失败与非 2xx 请求列表 / console 错误数 / 产物路径 / errors。**先读摘要判断页面是否正常，再按需读产物文件。**

### 产物开关（按需组合，全部可选）

| flag | 作用 |
|------|------|
| `--screenshot <path.png>` | 截图到 path |
| `--full-page` | 整页截图（配合 `--screenshot`） |
| `--har <path.har>` | 抓包：录制 HAR（**最完整**：含所有请求/响应头、body、时序，可导入 DevTools/Charles）。`--reuse-login`/普通模式可用；`--cdp` 模式不可用 |
| `--requests <path.json>` | 抓包：导出精简请求列表（method/url/status/type/耗时）。默认已含 `requestBody`（POST 提交内容） |
| `--response-headers` | 在 `--requests` 每条加响应头 |
| `--response-body` | 在 `--requests` 每条加响应体（JSON/文本类，单条上限 100KB，二进制标注跳过） |
| `--request-headers` | 在 `--requests` 每条加请求头 |
| `--console <path.json>` | 导出 console 日志与 pageerror |

### 行为控制

| flag | 作用 |
|------|------|
| `--wait <cssSelector>` | 导航后等该元素出现再截图/收网 |
| `--wait-ms <ms>` | 额外静置等待（等异步请求/动画） |
| `--viewport <WxH>` | 视口，默认 `1440x900` |
| `--timeout <ms>` | 导航超时，默认 30000 |
| `--headed` | 显示浏览器窗口（默认无头） |
| `--keep-open` | 显示窗口并保持打开，边手动操作边录，关窗或超时后落盘 |
| `--channel <chrome\|msedge\|chromium>` | 浏览器通道，默认 chrome |
| `--url-filter <regex>` | 摘要/requests 只保留 URL 匹配该正则的请求 |
| `--header <k:v>` | 追加请求头，可多次 |
| `--cookie <k=v;domain>` | 追加 cookie，可多次（domain 可选，默认取 URL host） |
| `--user-agent <ua>` | 覆盖 UA |

### 复用登录态（抓需要登录的页面）

| 方式 | flag | 说明 |
|------|------|------|
| **解密注入 cookie（推荐，非侵入，可无头）** | `--reuse-login` | 从 Chrome Cookies 库**只读**提取目标域 cookie，用 Keychain 密钥解密后注入独立浏览器。**不关也不碰你正在用的 Chrome**，可无头。首次会弹一次 Keychain 授权，点允许即可 |
| CDP 连接（会重启 Chrome） | `--cdp [--restart-chrome]` | 连调试端口 Chrome 复用登录。端口没开需 `--restart-chrome`，会**退出并重启你的 Chrome**（打扰性大，一般不用） |
| Chrome profile 复制 | `--chrome-profile` | 复制 profile 启动，对加密会话 cookie 常失败，**不推荐** |

**推荐用法——非侵入抓已登录页面（不动你的 Chrome、可无头）：**

```
node ~/.kiro/skills/web-probe/web-probe.mjs capture <已登录页面URL> \
  --reuse-login \
  --screenshot /tmp/p.png --requests /tmp/p.req.json --url-filter "/api/portal/" --wait-ms 4000
```

原理：读 `~/Library/Application Support/Google/Chrome/Default/Cookies`（只读、immutable），
用 macOS Keychain「Chrome Safe Storage」密钥 AES-128-CBC 解密，按目标域匹配后注入无头浏览器。
摘要 `errors` 里会列出注入了哪些 cookie。首次运行 `security` 会弹一次 Keychain 授权。
（完整实现原理见同目录 `HOW-IT-WORKS.md`，按需查阅，不自动进上下文。）

<callout>
⚠️ `--cdp --restart-chrome` 会退出并重启你的 Chrome，会关掉当前所有标签（虽随 profile 恢复）。
除非明确需要连真实浏览器交互，否则优先用 `--reuse-login`（不打扰、可无头）。
</callout>


## 典型用法（原子 & 组合）

原子——只截图：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/page --screenshot /tmp/p.png --full-page
```

原子——只抓包（用户说「访问 URL 然后抓包」）：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/page --har /tmp/p.har --requests /tmp/p.req.json
```

组合——截图 + 抓包 + console，并等接口加载完：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/list \
  --screenshot /tmp/p.png --har /tmp/p.har --console /tmp/p.log.json \
  --wait "[data-testid=list-loaded]" --wait-ms 800
```

只看某类接口（如只抓 /api/portal）：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/x \
  --requests /tmp/api.json --url-filter "/api/portal/"
```

带登录态抓包：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/x \
  --cookie "session=abc123" --header "X-Env:test" --har /tmp/p.har
```

交互式（自己点几下再落盘）：
```
node ~/.kiro/skills/web-probe/web-probe.mjs capture https://app.test/x --keep-open --har /tmp/p.har --screenshot /tmp/p.png --timeout 120000
```

## Agent 使用约定

- 截图产物用图片读取工具查看，用于**可视化验收**（布局、暗黑模式、空态等）。
- 抓包：先看 stdout 摘要的 `requests.failed` / `requests.non2xx` 快速定位问题；需要请求体/响应头细节时再读 HAR/requests。
- console：`console.errors > 0` 时读 `--console` 产物定位前端报错。
- 验证本地开发（`pnpm dev`）：直接对 `https://localhost:<port>` 抓，脚本已 `ignoreHTTPSErrors`。

### 产物路径与时间戳
- 产物 flag 的路径**可省略**：只写 `--screenshot --requests` 等，会自动落到
  `<out-dir>/<时间戳>/`（默认 `/tmp/web-probe/YYYYMMDD-HHMMSS/`，可用 `--out-dir` / `--tag` 定制）。
  一天多次运行各进各的时间戳目录，**不会互相覆盖/混乱**。
- 需要固定位置时再显式传路径（如 `--screenshot /tmp/p.png`）。
- stdout 摘要里的 `runDir` / `artifacts` 会告诉你产物落在哪。

### token 纪律（重要）
- 产物写的是**磁盘文件，不进上下文**；skill 只在 stdout 返回**精简摘要**（计数 + 失败/非2xx 上限 50，不含 body），所以**请求再多、响应再长都不会撑爆 token**。
- 真正耗 token 的是**读产物文件**。读 `requests.json` / HAR 时**必须挑着读**：
  用 `jq`/`grep`/`node -e` 只取需要的字段或某几条，**禁止把整个大文件 dump 进上下文**。
- 只在确有需要时才加 `--response-body`；配合 `--url-filter` 缩小到关心的接口。

## 已知限制

- 只能驱动 Chrome / Edge / Chromium，**无法使用任意品牌的 OS 默认浏览器**（Safari/Firefox 需另配）。
- `--keep-open` 依赖有图形界面的环境（本机 macOS 可用；纯 SSH 无显示时用无头 + `--wait`/`--wait-ms`）。
- HAR 只在浏览器上下文关闭时落盘（脚本已处理），中途 kill 进程会丢 HAR。
- **复用登录态**：优先 `--reuse-login`（只读解密 Chrome cookie 后注入，不碰你的 Chrome、可无头；首次弹一次 Keychain 授权）。`--cdp --restart-chrome` 会重启你的 Chrome，打扰大，仅在需连真实浏览器交互时用。`--chrome-profile` 复制法对加密会话 cookie 常失败，不推荐。
- `--cdp` 模式复用已存在上下文，**不支持 HAR**，抓包用 `--requests`。
- `--reuse-login` 依赖 macOS Keychain 与 `sqlite3`/`security` 命令（系统自带）；仅在 macOS 验证过。
