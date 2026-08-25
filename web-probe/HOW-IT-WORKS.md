# web-probe 登录态复用原理（--reuse-login）

> 本文档是按需查阅的实现说明，**不会被自动加载进对话上下文**（不占 token）。
> 需要回顾"为什么能复用登录、怎么解密的"时再读。

## 一句话

把你 Chrome 里存的登录 cookie **只读取出 → 用 Keychain 密钥解密 → 注入一个独立无头浏览器**，
从而复用登录态，全程不碰你正在用的 Chrome。

## 完整链路

### 1. Cookie 存在哪
Chrome 把 cookie 存在 SQLite 文件：
```
~/Library/Application Support/Google/Chrome/Default/Cookies
```
每行含 `host_key`（域）、`name`、`encrypted_value`（加密值）、`path`、`is_secure`、
`is_httponly`、`expires_utc` 等。登录态即某些域（如 `.test.tigerbrokers.net`）下的
会话 cookie（如 `tigo-dev-entra` / `tigo-entra`）。

用只读、immutable 模式读，不写不锁：
```
sqlite3 "file:<Cookies>?mode=ro&immutable=1" "SELECT ... FROM cookies;"
```

### 2. 值是加密的，密钥在 Keychain
`encrypted_value` 是 AES 加密、前缀 `v10`。解密密钥不在文件里，在 macOS 钥匙串条目
「Chrome Safe Storage」：
```
security find-generic-password -w -s "Chrome Safe Storage"
```
拿到密码串后派生 AES key（Chrome 在 macOS 的固定约定）：
```
key = PBKDF2-HMAC-SHA1(password, salt="saltysalt", iterations=1003, keylen=16)
```
> 首次运行 `security` 时系统弹的授权框，就是在确认"允许读取该钥匙串密钥"。点允许即可。

### 3. 解密单个 cookie 值
```
buf        = hex → bytes
去掉前 3 字节 "v10"
AES-128-CBC 解密，IV = 16 个 0x20（空格），key 见上
去掉 PKCS7 padding
（新版 mac Chrome 明文前可能有 32 字节 domain hash，含控制字符时跳过前 32 字节）
→ 得到明文 cookie 值
```

### 4. 域匹配 + 注入
按目标 URL 的 host 做 cookie 域匹配（`host === host_key` 或 `host` 以 `.host_key` 结尾），
把匹配到的已解密 cookie 通过 Playwright `context.addCookies()` 注入一个**全新无头 Chromium**，
再访问目标 URL。浏览器带着这些 cookie 请求 → 后端认会话 → 直接放行。

`expires_utc` 是"1601 年起的微秒"，转 Unix 秒：`floor(expires_utc/1e6 - 11644473600)`。

## 为什么不打扰你的 Chrome
- 只读 Cookies 文件（immutable），不写、不加锁；
- 跑的是**另一个独立无头浏览器进程**，用的是复制出来的明文 cookie；
- 你的 Chrome 照常开着，标签一个不动。

## 为什么"复制 profile"（--chrome-profile）会失败
把加密的 Cookies 文件整个搬到新 profile，新启动的 Chrome **解不开那串密文**
（涉及 profile 绑定 / app-bound 加密），cookie 变空 → 仍 401。
`--reuse-login` 则是**自己用钥匙串密钥手动解密成明文**再注入，绕过绑定 → 成功。

## 安全边界
- 全程本地操作，cookie 明文只在内存中用于注入，不落盘、不外发。
- 依赖 macOS 的 `security`（Keychain）与 `sqlite3`，仅在 macOS 验证。
- 首次需用户在系统弹窗授权读取 Keychain 密钥。

## 相关代码
`web-probe.mjs` 中的 `getSafeStorageKey` / `decryptChromeCookie` /
`cookieDomainMatch` / `extractChromeCookies`，以及 `--reuse-login` 注入分支。
