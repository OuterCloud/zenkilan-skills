#!/usr/bin/env node
/**
 * overflow-probe —— 定位「内容被裁 / 滚不动 / 横向显示不全」的真正源头。
 *
 * 用法:
 *   node overflow-probe.mjs <url> [options]
 *
 *   --viewport <WxH>     视口尺寸，默认 1440x900。窄屏问题必须显式传窄值，否则量不到。
 *   --from <selector>    从该元素开始向上量祖先链（默认量整页）
 *   --json <path>        把完整结果写到文件
 *   --screenshot <path>  截图
 *   --wait-ms <ms>       导航后静置时间，默认 3000（等 SPA 渲染）
 *   --cookie <k=v>       追加 cookie，可多次
 *   --chrome <path>      Chrome 可执行文件，默认 macOS 的 Google Chrome
 *   --strict             发现「被裁的溢出」时以退出码 1 结束（可用于 CI 门禁）
 *
 * 输出: 每个「内容比容器宽」的元素一行，带祖先链 / 计算样式 / 是否可滚动。
 * 关键判据见 SKILL.md「三类溢出」。
 */

import { spawn } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// 优先读 CHROME_PATH，便于 Linux CI 或非标准安装位置
const CHROME_PATH = process.env.CHROME_PATH
const CHROME_DEFAULT = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

function parseArgs(argv) {
  const opts = { viewport: "1440x900", waitMs: 3000, cookies: [], chrome: CHROME_PATH || CHROME_DEFAULT, strict: false }
  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i]
    if (!tok.startsWith("--")) { opts.url = tok; continue }
    const key = tok.slice(2)
    if (key === "strict") { opts.strict = true; continue }
    const val = argv[++i]
    if (val === undefined) throw new Error(`--${key} 缺少值`)
    if (key === "viewport") opts.viewport = val
    else if (key === "from") opts.from = val
    else if (key === "json") opts.json = val
    else if (key === "screenshot") opts.screenshot = val
    else if (key === "wait-ms") opts.waitMs = Number(val)
    else if (key === "cookie") opts.cookies.push(val)
    else if (key === "chrome") opts.chrome = val
    else throw new Error(`未知参数 --${key}`)
  }
  if (!opts.url) throw new Error("缺少 url")
  return opts
}

/** 启动一个独立的无头 Chrome，返回 { wsUrl, close }。不碰用户正在用的 Chrome。 */
function launchChrome(bin) {
  return new Promise((resolve, reject) => {
    const dir = mkdtempSync(join(tmpdir(), "overflow-probe-"))
    const proc = spawn(bin, [
      "--headless=new", "--disable-gpu", "--ignore-certificate-errors",
      "--remote-debugging-port=0", `--user-data-dir=${dir}`, "about:blank",
    ], { stdio: ["ignore", "ignore", "pipe"] })
    let buf = ""
    let settled = false
    // 这个定时器必须清掉：否则脚本跑完后进程被它吊住，白白多等 20 秒才退出
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      proc.kill()
      reject(new Error("Chrome 启动超时"))
    }, 20000)
    const onData = (chunk) => {
      buf += chunk.toString()
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/)
      if (!m || settled) return
      settled = true
      clearTimeout(timer)
      proc.stderr.off("data", onData)
      resolve({ wsUrl: m[1], proc })
    }
    proc.stderr.on("data", onData)
    proc.on("exit", (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(new Error(`Chrome 退出，code=${code}`))
    })
  })
}

/*
  一条 ws 上可能挂着多个 session（browser 级 + 某个 page）。
  CDP 的响应只回到 ws，所以 pending 表必须共享；
  谁发的命令是靠 payload.sessionId 区分，不是靠各自记一份将来接收。
*/
class CDP {
  constructor(ws, shared, sessionId) {
    this.ws = ws
    this.pending = shared.pending
    this.counter = shared.counter
    this.sessionId = sessionId
  }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl)
    await new Promise((res, rej) => {
      ws.addEventListener("open", res, { once: true })
      ws.addEventListener("error", () => rej(new Error("CDP 连接失败")), { once: true })
    })
    const pending = new Map()
    const counter = { n: 0 }
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data)
      const waiter = msg.id && pending.get(msg.id)
      if (waiter) { waiter(msg); pending.delete(msg.id) }
    })
    return new CDP(ws, { pending, counter }, null)
  }
  send(method, params = {}) {
    const id = ++this.counter.n
    const payload = { id, method, params }
    if (this.sessionId) payload.sessionId = this.sessionId
    return new Promise((res) => { this.pending.set(id, res); this.ws.send(JSON.stringify(payload)) })
  }
  /** 建一页并把后续命令绑到它的 session；browser 级 endpoint 不能直接调 Page 域。 */
  async openPage() {
    const created = await this.send("Target.createTarget", { url: "about:blank" })
    const targetId = created.result?.targetId
    if (!targetId) throw new Error(`创建页面失败: ${created.error?.message || "未知原因"}`)
    const attached = await this.send("Target.attachToTarget", { targetId, flatten: true })
    const sessionId = attached.result?.sessionId
    if (!sessionId) throw new Error(`附加页面失败: ${attached.error?.message || "未知原因"}`)
    return new CDP(this.ws, { pending: this.pending, counter: this.counter }, sessionId)
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })
    if (r.error) throw new Error(`CDP 错误: ${r.error.message}`)
    const ex = r.result?.exceptionDetails
    if (ex) throw new Error(`页面内执行失败: ${ex.exception?.description || ex.text}`)
    return r.result?.result?.value
  }
}

/*
  页面内测量：找出所有「内容比容器宽」的元素。

  只报告 scrollWidth > clientWidth + 1 的元素，因为那才是真的有溢出；
  再按「父级 overflow-x 是否 visible」判断它是不是滚动容器，从而分成
  scrollable（能滚）和 clipped（被裁）。clipped 就是用户看不见又滚不到的那种。
*/
const MEASURE_JS = (fromSelector) => `(() => {
  const describe = (el) => {
    if (!el) return null
    const cs = getComputedStyle(el)
    const r = el.getBoundingClientRect()
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      cls: el.className && typeof el.className === "string" ? el.className.slice(0, 120) : undefined,
      w: Math.round(r.width),
      clientWidth: el.clientWidth,
      scrollWidth: el.scrollWidth,
      overflowX: cs.overflowX,
      overflowY: cs.overflowY,
      minWidth: cs.minWidth,
      display: cs.display,
      flex: cs.flex,
      position: cs.position,
    }
  }

  const roots = ${fromSelector ? `[document.querySelector(${JSON.stringify(fromSelector)})].filter(Boolean)` : "[document.body]"}
  if (!roots.length) return { error: "找不到 --from 指定的元素" }

  const findings = []
  const seen = new Set()
  const skip = new Set(["SCRIPT", "STYLE", "HEAD", "META", "LINK", "TITLE"])

  // --from 只量指定区域时，最容易漏掉「裁切点在区域外面」这种情况（本次事故就是这样）。
  // 所以区域自己的祖先链必须单独扫一遍，否则用户会得到一个「没有发现溢出」的假结论。
  if (${fromSelector ? "true" : "false"}) {
    for (const el of [roots[0].parentElement, ...(() => { const out = []; let p = roots[0].parentElement?.parentElement; for (let i = 0; i < 20 && p; i++, p = p.parentElement) out.push(p); return out })()]) {
      if (!el || skip.has(el.tagName) || seen.has(el)) continue
      const over = el.scrollWidth - el.clientWidth
      const cs = getComputedStyle(el)
      if (over <= 1 || cs.overflowX === "visible") continue
      seen.add(el)
      findings.push({
        kind: cs.overflowX === "hidden" || cs.overflowX === "clip" ? "clipped" : "scrollable",
        overflowBy: over,
        outsideFrom: true,
        self: describe(el),
        ancestors: [],
      })
    }
  }

  for (const root of roots) {
    const all = [root, ...root.querySelectorAll("*")]
    for (const el of all) {
      if (skip.has(el.tagName)) continue
      const over = el.scrollWidth - el.clientWidth
      if (over <= 1) continue
      if (seen.has(el)) continue
      seen.add(el)
      const cs = getComputedStyle(el)
      // overflow-x visible 表示「溢出会交给上层」，既不是滚动容器也不是裁切点，跳过
      if (cs.overflowX === "visible") continue
      findings.push({
        kind: cs.overflowX === "hidden" || cs.overflowX === "clip" ? "clipped" : "scrollable",
        overflowBy: over,
        self: describe(el),
        ancestors: (() => { const out = []; let p = el.parentElement; for (let i = 0; i < 4 && p; i++, p = p.parentElement) out.push(describe(p)); return out })(),
      })
    }
  }
  findings.sort((a, b) => (a.kind === b.kind ? b.overflowBy - a.overflowBy : a.kind === "clipped" ? -1 : 1))
  return {
    viewport: { w: innerWidth, h: innerHeight },
    doc: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight },
    clippedCount: findings.filter((f) => f.kind === "clipped").length,
    findings,
  }
})()`

function printReport(result) {
  const { viewport, doc, findings, clippedCount } = result
  console.log(`视口 ${viewport.w}x${viewport.h} · 文档 clientWidth=${doc.clientWidth} scrollWidth=${doc.scrollWidth}`)
  if (!findings.length) { console.log("没有发现横向溢出容器。"); return }
  console.log(`发现 ${findings.length} 个横向溢出容器，其中 ${clippedCount} 个被裁切（内容看不见也滚不到）\n`)
  for (const f of findings) {
    const s = f.self
    const tag = `${s.tag}${s.id ? "#" + s.id : ""}${s.cls ? "." + s.cls.split(/\s+/).slice(0, 3).join(".") : ""}`
    const mark = f.kind === "clipped" ? "❌ 被裁" : "→ 可滚动"
    console.log(`${mark}  溢出 ${f.overflowBy}px  ${tag}${f.outsideFrom ? "（在 --from 区域外层，正是它裁掉了你关心的内容）" : ""}`)
    console.log(`        client=${s.clientWidth} scroll=${s.scrollWidth} w=${s.w} overflow-x=${s.overflowX} min-width=${s.minWidth} display=${s.display}`)
    if (f.kind === "clipped") {
      console.log("        祖先链（找第一个 overflow-x: hidden 的就是裁切点）:")
      for (const a of f.ancestors) {
        if (!a) continue
        console.log(`          ${a.tag}${a.cls ? "." + a.cls.split(/\s+/).slice(0, 2).join(".") : ""}  w=${a.w} client=${a.clientWidth} scroll=${a.scrollWidth} overflow-x=${a.overflowX} min-width=${a.minWidth}`)
      }
    }
    console.log()
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  const [w, h] = opts.viewport.split("x").map(Number)
  const { wsUrl, proc } = await launchChrome(opts.chrome)
  try {
    const browser = await CDP.connect(wsUrl)
    const cdp = await browser.openPage()
    await cdp.send("Page.enable")
    await cdp.send("Network.enable")
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false })
    if (opts.cookies.length) {
      const host = new URL(opts.url).hostname
      const cookies = opts.cookies.map((c) => {
        const [kv, domain] = c.split(";")
        const idx = kv.indexOf("=")
        return { name: kv.slice(0, idx), value: kv.slice(idx + 1), domain: domain || host, path: "/" }
      })
      await cdp.send("Network.setCookies", { cookies })
    }
    await cdp.send("Page.navigate", { url: opts.url })
    await new Promise((r) => setTimeout(r, opts.waitMs))
    const result = await cdp.eval(MEASURE_JS(opts.from))
    if (result?.error) throw new Error(result.error)
    printReport(result)
    if (opts.json) { writeFileSync(opts.json, JSON.stringify(result, null, 2)); console.log(`完整结果: ${opts.json}`) }
    if (opts.screenshot) {
      const shot = await cdp.send("Page.captureScreenshot", { format: "png" })
      writeFileSync(opts.screenshot, Buffer.from(shot.result.data, "base64"))
      console.log(`截图: ${opts.screenshot}`)
    }
    if (opts.strict && result.clippedCount > 0) process.exitCode = 1
  } finally {
    proc.kill()
  }
}

main().catch((e) => { console.error("overflow-probe 失败:", e.message); process.exit(2) })
