#!/usr/bin/env node
/**
 * web-probe —— 前端自动化验证工具
 *
 * 用 Playwright 驱动本机 Chrome：打开 URL、截图、抓网络请求（HAR/JSON）、收集 console。
 * 每个产物都是独立开关，可原子使用也可任意组合。
 *
 * 用法：
 *   node web-probe.mjs capture <url> [flags]
 *   node web-probe.mjs chrome-debug [--restart-chrome]   # 仅确保调试端口 Chrome 就绪
 *
 * 复用登录态（抓需登录页面）：
 *   --reuse-login         从 Chrome Cookies 库解密提取目标域 cookie 并注入（非侵入、可无头，推荐）
 *   --cdp [--restart-chrome]  连调试端口 Chrome（--restart-chrome 会重启你的 Chrome，打扰大）
 *   --cdp-endpoint <url>  调试端口地址，默认 http://127.0.0.1:9222
 *   --chrome-profile      复制 profile 启动（对加密会话 cookie 常失败，不推荐）
 *
 * 常用 flags（全部可选，按需组合）：
 *   --screenshot <path>   截图保存到 path（.png）
 *   --full-page           整页截图（配合 --screenshot）
 *   --har <path>          抓包：录制 HAR 到 path（含请求/响应/时序）
 *   --requests <path>     抓包：导出精简请求列表 JSON 到 path
 *   --console <path>      导出 console 日志 JSON 到 path
 *   --wait <selector>     导航后等待某 CSS selector 出现再截图/收网
 *   --wait-ms <ms>        额外静置等待毫秒数（默认 0）
 *   --viewport <WxH>      视口尺寸，如 1440x900（默认 1440x900）
 *   --timeout <ms>        导航超时（默认 30000）
 *   --headed              显示浏览器窗口（默认无头）
 *   --keep-open           显示窗口并保持打开，边操作边录，直到关闭窗口或 --timeout 到时
 *   --channel <name>      浏览器通道 chrome|msedge|chromium（默认 chrome，用系统已装浏览器）
 *   --url-filter <regex>  只在 stdout 摘要/requests JSON 中保留 URL 匹配该正则的请求
 *   --header <k:v>        额外请求头，可多次
 *   --cookie <k=v;domain> 追加 cookie，可多次（domain 可选，默认取 URL host）
 *   --user-agent <ua>     覆盖 UA
 *
 * stdout 始终输出一段 JSON 摘要（title、请求数、失败/非2xx 列表、console 错误数、产物路径）。
 */

import { chromium } from "playwright-core"
import { mkdir, cp } from "node:fs/promises"
import { existsSync } from "node:fs"
import { dirname, join } from "node:path"
import { homedir, tmpdir } from "node:os"
import { spawn, execSync } from "node:child_process"
import crypto from "node:crypto"

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

// macOS 默认 Chrome 用户数据目录
function defaultChromeUserDataDir() {
  return join(homedir(), "Library", "Application Support", "Google", "Chrome")
}

// ---------- 从 Chrome Cookies 库解密提取 cookie（非侵入，只读，可无头）----------

// 取 macOS Keychain 里的「Chrome Safe Storage」密钥并派生 AES key（首次会弹一次授权）
function getSafeStorageKey() {
  const pw = execSync(`security find-generic-password -w -s "Chrome Safe Storage"`, {
    encoding: "utf8",
  }).trim()
  return crypto.pbkdf2Sync(pw, "saltysalt", 1003, 16, "sha1")
}

function decryptChromeCookie(hexVal, key) {
  const buf = Buffer.from(hexVal, "hex")
  if (buf.length === 0) return ""
  const prefix = buf.subarray(0, 3).toString("latin1")
  if (prefix !== "v10" && prefix !== "v11") return null // 非预期格式，跳过
  const iv = Buffer.alloc(16, 0x20)
  const decipher = crypto.createDecipheriv("aes-128-cbc", key, iv)
  decipher.setAutoPadding(false)
  let out = Buffer.concat([decipher.update(buf.subarray(3)), decipher.final()])
  const pad = out[out.length - 1]
  if (pad > 0 && pad <= 16) out = out.subarray(0, out.length - pad)
  let val = out.toString("utf8")
  // 新版 Chrome(mac) 明文前可能有 32 字节 domain hash：含控制字符时跳过前 32 字节
  if (/[\u0000-\u0008\u000e-\u001f]/.test(val) && out.length > 32) {
    val = out.subarray(32).toString("utf8")
  }
  return val
}

// cookie 域匹配：host 是否应收到 host_key 的 cookie
function cookieDomainMatch(host, hostKey) {
  const hk = hostKey.startsWith(".") ? hostKey.slice(1) : hostKey
  return host === hk || host.endsWith("." + hk)
}

/** 从默认 Chrome profile 提取匹配目标 URL 的 cookie（已解密），供注入 */
function extractChromeCookies(url, udd, profile) {
  const host = new URL(url).hostname
  const db = [join(udd, profile, "Cookies"), join(udd, profile, "Network", "Cookies")].find(existsSync)
  if (!db) throw new Error(`未找到 Cookies 库: ${join(udd, profile)}`)
  const sql =
    "SELECT host_key||char(9)||name||char(9)||path||char(9)||is_secure||char(9)||is_httponly||char(9)||expires_utc||char(9)||hex(encrypted_value) FROM cookies;"
  const raw = execSync(`sqlite3 "file:${db}?mode=ro&immutable=1" ${JSON.stringify(sql)}`, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  })
  const key = getSafeStorageKey()
  const cookies = []
  for (const line of raw.split("\n")) {
    if (!line) continue
    const [hostKey, name, path, isSecure, isHttpOnly, expiresUtc, hexv] = line.split("\t")
    if (!cookieDomainMatch(host, hostKey)) continue
    const value = decryptChromeCookie(hexv, key)
    if (value == null || value === "") continue
    const c = {
      name,
      value,
      domain: hostKey,
      path: path || "/",
      secure: isSecure === "1",
      httpOnly: isHttpOnly === "1",
    }
    const exp = Number(expiresUtc)
    if (exp > 0) {
      const unix = Math.floor(exp / 1e6 - 11644473600)
      if (unix > 0) c.expires = unix
    }
    cookies.push(c)
  }
  return cookies
}

// ---------- CDP 自举：确保有一个开了调试端口的 Chrome ----------
async function isCdpUp(endpoint) {
  try {
    const u = new URL(endpoint)
    const res = await fetch(`http://${u.hostname}:${u.port || 9222}/json/version`, {
      signal: AbortSignal.timeout(1500),
    })
    return res.ok
  } catch {
    return false
  }
}

function isChromeRunning() {
  try {
    execSync('pgrep -x "Google Chrome"', { stdio: "ignore" })
    return true
  } catch {
    return false
  }
}

async function quitChrome() {
  try {
    execSync(`osascript -e 'tell application "Google Chrome" to quit'`, { stdio: "ignore" })
  } catch { /* ignore */ }
  for (let i = 0; i < 40; i++) {
    if (!isChromeRunning()) return true
    await sleep(250)
  }
  return !isChromeRunning()
}

function launchDebugChrome(port, userDataDir) {
  const child = spawn(
    CHROME_BIN,
    [
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userDataDir}`,
      "--restore-last-session",
      "--no-first-run",
      "--no-default-browser-check",
    ],
    { detached: true, stdio: "ignore" }
  )
  child.unref()
}

/**
 * 确保存在一个可连接的调试端口 Chrome，复用用户默认 profile（含登录态）。
 * - 端口已就绪 → 直接复用
 * - Chrome 未运行 → 直接以调试端口启动
 * - Chrome 在运行但没开调试端口 → 需 restart=true，本工具会优雅退出它再以调试端口重启
 *   （会话/标签/登录随 profile 保留，重启带 --restore-last-session）
 */
async function ensureChromeCdp(endpoint, { restart }) {
  if (await isCdpUp(endpoint)) return { reused: true }
  const u = new URL(endpoint)
  const port = u.port || "9222"
  const running = isChromeRunning()
  if (running && !restart) {
    return {
      error:
        "Chrome 正在运行但未开调试端口。加 --restart-chrome，本工具会优雅退出并以调试端口重启 Chrome（标签/登录随 profile 保留、自动恢复上次会话）。",
    }
  }
  if (running) {
    const ok = await quitChrome()
    if (!ok) return { error: "退出现有 Chrome 超时失败，请手动退出后重试。" }
  }
  launchDebugChrome(port, defaultChromeUserDataDir())
  for (let i = 0; i < 40; i++) {
    if (await isCdpUp(endpoint)) return { launched: true }
    await sleep(500)
  }
  return { error: `已尝试以调试端口启动 Chrome，但 ${endpoint} 在 20s 内未就绪。` }
}

/**
 * 复制 Chrome profile 的登录关键文件到临时 user-data-dir。
 *
 * 为什么复制而不是直接用原目录：Chrome 正在运行时会锁定原 user-data-dir，
 * 直接启动会冲突。cookie 值用 Keychain「Chrome Safe Storage」密钥加密，
 * 与 profile 路径无关，故复制出来后用同一个 Chrome（channel chrome）仍可解密，
 * 登录态得以保留，且不打扰用户正在使用的 Chrome。
 */
async function makeProfileCopy(srcUdd, profile) {
  const tmp = join(tmpdir(), `web-probe-udd-${Date.now()}`)
  const dstProfile = join(tmp, profile)
  await mkdir(join(dstProfile, "Network"), { recursive: true })
  const copies = [
    ["Local State", join(srcUdd, "Local State"), join(tmp, "Local State")],
    ["Cookies", join(srcUdd, profile, "Cookies"), join(dstProfile, "Cookies")],
    ["Network/Cookies", join(srcUdd, profile, "Network", "Cookies"), join(dstProfile, "Network", "Cookies")],
    ["Preferences", join(srcUdd, profile, "Preferences"), join(dstProfile, "Preferences")],
    ["Secure Preferences", join(srcUdd, profile, "Secure Preferences"), join(dstProfile, "Secure Preferences")],
  ]
  const copied = []
  for (const [label, from, to] of copies) {
    if (existsSync(from)) {
      await cp(from, to).catch(() => {})
      copied.push(label)
    }
  }
  return { tmp, copied }
}

// ---------- 极简 arg 解析（支持 flag 带值 / 布尔 / 可重复） ----------
function parseArgs(argv) {
  const stringFlags = new Set([
    "wait", "wait-ms",
    "viewport", "timeout", "channel", "url-filter", "user-agent",
    "user-data-dir", "profile", "cdp-endpoint", "out-dir", "tag",
  ])
  // 产物类 flag：值可选。给了路径就用路径；只写 --xxx（后面没值或是下一个 flag）则启用+自动时间戳命名
  const optionalValueFlags = new Set(["screenshot", "har", "requests", "console"])
  const boolFlags = new Set(["full-page", "headed", "keep-open", "chrome-profile", "cdp", "restart-chrome", "reuse-login", "request-headers", "response-headers", "response-body"])
  const repeatFlags = new Set(["header", "cookie"])
  const out = { _: [], header: [], cookie: [] }
  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i]
    if (tok.startsWith("--")) {
      const key = tok.slice(2)
      if (boolFlags.has(key)) { out[key] = true; continue }
      if (optionalValueFlags.has(key)) {
        const next = argv[i + 1]
        if (next === undefined || next.startsWith("--")) {
          out[key] = true // 启用，自动命名
        } else {
          out[key] = next // 显式路径
          i++
        }
        continue
      }
      if (stringFlags.has(key) || repeatFlags.has(key)) {
        const val = argv[++i]
        if (val === undefined) throw new Error(`flag --${key} 缺少值`)
        if (repeatFlags.has(key)) out[key].push(val)
        else out[key] = val
        continue
      }
      throw new Error(`未知 flag: --${key}`)
    } else {
      out._.push(tok)
    }
  }
  return out
}

async function ensureDir(filePath) {
  await mkdir(dirname(filePath), { recursive: true }).catch(() => {})
}

function parseViewport(s) {
  const m = /^(\d+)x(\d+)$/.exec(s ?? "")
  return m ? { width: +m[1], height: +m[2] } : { width: 1440, height: 900 }
}

function tsStamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, "0")
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/**
 * 解析产物路径：
 * - flag 值是字符串 → 用显式路径
 * - flag 值是 true（只写了 --xxx）→ 自动写到 runDir 下的默认名（带时间戳目录，避免多次运行覆盖/混乱）
 * - 未启用 → null
 */
function resolveArtifact(flagVal, runDir, defName) {
  if (typeof flagVal === "string") return flagVal
  if (flagVal === true) return join(runDir, defName)
  return null
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const cmd = args._[0]
  const url = args._[1]

  // 子命令：仅确保调试端口 Chrome 就绪（复用登录态的前置，内部闭环用）
  if (cmd === "chrome-debug") {
    const ep = args["cdp-endpoint"] || "http://127.0.0.1:9222"
    const r = await ensureChromeCdp(ep, { restart: !!args["restart-chrome"] })
    console.log(JSON.stringify({ endpoint: ep, ...r }, null, 2))
    process.exit(r.error ? 1 : 0)
  }

  if (cmd !== "capture" || !url) {
    console.error("用法: node web-probe.mjs capture <url> [flags] | chrome-debug [--restart-chrome]（见文件头注释）")
    process.exit(2)
  }

  const viewport = parseViewport(args.viewport)
  const timeout = Number(args.timeout ?? 30000)
  const channel = args.channel ?? "chrome"
  const keepOpen = !!args["keep-open"]
  const urlFilter = args["url-filter"] ? new RegExp(args["url-filter"]) : null
  const useProfile = !!(args["chrome-profile"] || args["user-data-dir"])
  // 复用 Chrome 登录态时必须有界面（headed）；持久上下文不支持无头 + 已登录 cookie 的干净复用
  const headed = keepOpen || !!args.headed || useProfile

  // 组装额外请求头
  const extraHeaders = {}
  for (const h of args.header) {
    const idx = h.indexOf(":")
    if (idx > 0) extraHeaders[h.slice(0, idx).trim()] = h.slice(idx + 1).trim()
  }

  const summary = {
    url, title: null, ok: false, status: null,
    requests: { total: 0, failed: [], non2xx: [] },
    console: { total: 0, errors: 0 },
    artifacts: {},
    errors: [],
  }

  // 每次运行一个带时间戳的产物目录，避免一天多次运行相互覆盖/混乱。
  // 显式给了产物路径的仍按显式路径走；只写 --screenshot 之类则落到本目录。
  const outDir = args["out-dir"] || "/tmp/web-probe"
  const runDir = join(outDir, `${tsStamp()}${args.tag ? "-" + args.tag : ""}`)
  const screenshotPath = resolveArtifact(args.screenshot, runDir, "screenshot.png")
  const harPath = resolveArtifact(args.har, runDir, "network.har")
  const requestsPath = resolveArtifact(args.requests, runDir, "requests.json")
  const consolePath = resolveArtifact(args.console, runDir, "console.json")
  summary.runDir = runDir

  const contextOpts = { viewport, ignoreHTTPSErrors: true }
  if (args["user-agent"]) contextOpts.userAgent = args["user-agent"]
  if (Object.keys(extraHeaders).length) contextOpts.extraHTTPHeaders = extraHeaders
  if (harPath) {
    await ensureDir(harPath)
    contextOpts.recordHar = { path: harPath, content: "embed" }
    summary.artifacts.har = harPath
  }

  let browser = null
  let context
  let cdpMode = false

  if (args.cdp) {
    // ---- 连接到已在运行、且开启了调试端口的 Chrome，复用其登录态 ----
    const ep = args["cdp-endpoint"] || "http://127.0.0.1:9222"
    cdpMode = true
    // 内部闭环：端口没开就按需（--restart-chrome 授权下）自动重启 Chrome 到调试端口
    const ensured = await ensureChromeCdp(ep, { restart: !!args["restart-chrome"] })
    if (ensured.error) {
      console.log(JSON.stringify({ ...summary, errors: [ensured.error] }, null, 2))
      process.exit(1)
    }
    if (ensured.launched) summary.errors.push("已以调试端口启动/重启 Chrome（复用默认 profile 登录态）")
    try {
      browser = await chromium.connectOverCDP(ep)
    } catch (e) {
      console.log(JSON.stringify({ ...summary, errors: [`无法连接 CDP ${ep}: ${e.message}`] }, null, 2))
      process.exit(1)
    }
    // 复用已存在的上下文（含登录 cookie）；HAR 无法挂到已存在上下文，用 requests JSON 抓包
    context = browser.contexts()[0] ?? (await browser.newContext(contextOpts))
    if (harPath) summary.errors.push("CDP 模式不支持 HAR（上下文已存在），请用 --requests 抓包")
  } else if (useProfile) {
    // ---- 复用已登录的 Chrome profile（持久上下文）----
    const srcUdd = args["user-data-dir"] || defaultChromeUserDataDir()
    const profile = args.profile || "Default"
    if (!existsSync(srcUdd)) {
      console.log(JSON.stringify({ ...summary, errors: [`未找到 Chrome 用户数据目录: ${srcUdd}`] }, null, 2))
      process.exit(1)
    }
    const { tmp, copied } = await makeProfileCopy(srcUdd, profile)
    summary.errors.push(`复用 Chrome profile「${profile}」，已复制: ${copied.join(", ") || "（无 cookie 文件）"}`)
    try {
      context = await chromium.launchPersistentContext(tmp, {
        ...contextOpts,
        channel,
        headless: false,
        args: [`--profile-directory=${profile}`],
      })
    } catch (e) {
      console.log(JSON.stringify({ ...summary, errors: [...summary.errors, `持久上下文启动失败: ${e.message}`] }, null, 2))
      process.exit(1)
    }
  } else {
    // ---- 普通模式：无头/有头，全新上下文 ----
    try {
      browser = await chromium.launch({ channel, headless: !headed })
    } catch (e) {
      try {
        browser = await chromium.launch({ headless: !headed })
        summary.errors.push(`channel=${channel} 启动失败，已回退 bundled chromium: ${e.message}`)
      } catch (e2) {
        console.log(JSON.stringify({ ...summary, errors: [...summary.errors, `浏览器启动失败: ${e2.message}`] }, null, 2))
        process.exit(1)
      }
    }
    context = await browser.newContext(contextOpts)
  }

  // cookies
  if (args.cookie.length) {
    const host = new URL(url).hostname
    const cookies = args.cookie.map((c) => {
      const [kv, domain] = c.split(";").map((x) => x.trim())
      const eq = kv.indexOf("=")
      return {
        name: kv.slice(0, eq),
        value: kv.slice(eq + 1),
        domain: domain || host,
        path: "/",
      }
    })
    await context.addCookies(cookies).catch((e) => summary.errors.push(`addCookies: ${e.message}`))
  }

  // 非侵入复用登录态：从 Chrome Cookies 库解密提取目标域 cookie 并注入（不碰用户 Chrome，可无头）
  if (args["reuse-login"]) {
    try {
      const udd = args["user-data-dir"] || defaultChromeUserDataDir()
      const profile = args.profile || "Default"
      const extracted = extractChromeCookies(url, udd, profile)
      if (extracted.length) {
        await context.addCookies(extracted)
        summary.errors.push(
          `已从 Chrome 注入 ${extracted.length} 个 cookie: ${extracted.map((c) => c.name).join(", ")}`
        )
      } else {
        summary.errors.push("reuse-login: 未在 Chrome 找到该域名的 cookie（登录态可能不在此 profile）")
      }
    } catch (e) {
      summary.errors.push(`reuse-login 失败: ${e.message}（首次需在弹窗允许访问 Keychain）`)
    }
  }

  // CDP 模式：开新 tab，避免劫持用户正在看的标签页；
  // 持久 profile 模式：复用默认页；普通模式：新建页
  const page = cdpMode
    ? await context.newPage()
    : (context.pages()[0] ?? (await context.newPage()))
  if (cdpMode) {
    // 已存在上下文不吃 contextOpts.viewport，单独给 page 设
    await page.setViewportSize(viewport).catch(() => {})
  }

  // ---------- 网络抓包（内存收集，用于摘要 + requests JSON） ----------
  const reqList = []
  const reqStart = new Map()
  const bodyJobs = [] // --response-body 时异步取 body 的任务，写文件前统一 await
  const wantReqHeaders = !!args["request-headers"]
  const wantRespHeaders = !!args["response-headers"]
  const wantRespBody = !!args["response-body"]
  const BODY_CAP = 100_000

  page.on("request", (r) => reqStart.set(r, Date.now()))
  page.on("response", (resp) => {
    const req = resp.request()
    const u = resp.url()
    if (urlFilter && !urlFilter.test(u)) return
    const started = reqStart.get(req)
    const entry = {
      method: req.method(),
      url: u,
      status: resp.status(),
      resourceType: req.resourceType(),
      fromCache: resp.fromServiceWorker?.() ?? false,
      durationMs: started ? Date.now() - started : null,
    }
    // 请求体（POST/PUT 等提交内容）自动带上，抓包看"提交了啥"很有用
    const pd = req.postData()
    if (pd) entry.requestBody = pd.length > BODY_CAP ? pd.slice(0, BODY_CAP) + "…[truncated]" : pd
    if (wantReqHeaders) entry.requestHeaders = req.headers()
    if (wantRespHeaders) entry.responseHeaders = resp.headers()
    if (wantRespBody) {
      const ct = resp.headers()["content-type"] || ""
      if (/json|text|xml|javascript|html|urlencoded/i.test(ct)) {
        const job = resp
          .text()
          .then((t) => {
            entry.responseBody = t.length > BODY_CAP ? t.slice(0, BODY_CAP) + "…[truncated]" : t
          })
          .catch((e) => {
            entry.responseBody = `[unavailable: ${e.message}]`
          })
        bodyJobs.push(job)
      } else {
        entry.responseBody = `[binary omitted: ${ct || "unknown"}]`
      }
    }
    reqList.push(entry)
  })
  page.on("requestfailed", (req) => {
    const u = req.url()
    if (urlFilter && !urlFilter.test(u)) return
    reqList.push({
      method: req.method(), url: u, status: null,
      resourceType: req.resourceType(),
      failure: req.failure()?.errorText ?? "failed", durationMs: null,
    })
  })

  // ---------- console 收集 ----------
  const consoleLogs = []
  page.on("console", (msg) => {
    consoleLogs.push({ type: msg.type(), text: msg.text() })
  })
  page.on("pageerror", (err) => {
    consoleLogs.push({ type: "pageerror", text: err.message })
  })

  // ---------- 导航 ----------
  try {
    const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout })
    summary.status = resp?.status() ?? null
    summary.ok = resp?.ok() ?? false
  } catch (e) {
    summary.errors.push(`导航失败: ${e.message}`)
  }

  if (args.wait) {
    await page.waitForSelector(args.wait, { timeout }).catch((e) =>
      summary.errors.push(`等待 selector "${args.wait}" 失败: ${e.message}`)
    )
  }
  if (args["wait-ms"]) await page.waitForTimeout(Number(args["wait-ms"]))

  // keep-open：保持窗口，直到用户关闭或超时
  if (keepOpen) {
    summary.errors.push("keep-open 模式：请在浏览器中操作，完成后关闭窗口以结束录制")
    await new Promise((resolve) => {
      let done = false
      const finish = () => { if (!done) { done = true; resolve() } }
      page.on("close", finish)
      context.on("close", finish)
      browser.on("disconnected", finish)
      setTimeout(finish, timeout)
    })
  }

  try { summary.title = await page.title() } catch { /* page 可能已关闭 */ }

  // ---------- 截图 ----------
  if (screenshotPath) {
    await ensureDir(screenshotPath)
    try {
      await page.screenshot({ path: screenshotPath, fullPage: !!args["full-page"] })
      summary.artifacts.screenshot = screenshotPath
    } catch (e) {
      summary.errors.push(`截图失败: ${e.message}`)
    }
  }

  // 等待 --response-body 的异步 body 抓取完成（有超时保护，避免个别请求悬挂）
  if (bodyJobs.length) {
    await Promise.race([
      Promise.allSettled(bodyJobs),
      sleep(8000),
    ])
  }

  // ---------- 汇总网络 ----------
  summary.requests.total = reqList.length
  summary.requests.failed = reqList.filter((r) => r.failure).map((r) => ({ url: r.url, failure: r.failure })).slice(0, 50)
  summary.requests.non2xx = reqList.filter((r) => r.status && (r.status < 200 || r.status >= 300)).map((r) => ({ url: r.url, status: r.status })).slice(0, 50)
  summary.console.total = consoleLogs.length
  summary.console.errors = consoleLogs.filter((c) => c.type === "error" || c.type === "pageerror").length

  if (requestsPath) {
    await ensureDir(requestsPath)
    const { writeFile } = await import("node:fs/promises")
    await writeFile(requestsPath, JSON.stringify(reqList, null, 2))
    summary.artifacts.requests = requestsPath
  }
  if (consolePath) {
    await ensureDir(consolePath)
    const { writeFile } = await import("node:fs/promises")
    await writeFile(consolePath, JSON.stringify(consoleLogs, null, 2))
    summary.artifacts.console = consolePath
  }

  // 必须 close context 才会 flush HAR
  // 清理：CDP 模式只关自己开的 tab（不动用户的 Chrome）；其余模式关上下文/浏览器
  if (cdpMode) {
    await page.close().catch(() => {})
    // connectOverCDP 的 browser.close 只断开连接，不杀用户 Chrome
    await browser.close().catch(() => {})
  } else {
    await context.close().catch(() => {})
    if (browser) await browser.close().catch(() => {})
  }

  console.log(JSON.stringify(summary, null, 2))
}

main().catch((e) => {
  console.error(JSON.stringify({ fatal: e.message }, null, 2))
  process.exit(1)
})
