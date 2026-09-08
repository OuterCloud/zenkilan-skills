---
name: feishu-chat-collab
version: 1.0.0
description: "飞书群聊协作/机器人：让 AI 在飞书群里「读别人回复 → 分析 → 拟回复 → 发送（能 @人、带链接）」，按需触发、无需实时值守。发消息走群自定义机器人 Webhook（发 interactive 卡片 + lark_md），读消息走 lark-cli（以用户身份读自己所在的群）。当用户要把某个群的最新讨论读出来分析、拟一条群回复、或让机器人往群里推消息/卡片时使用。不负责：飞书云文档（feishu-doc-collab）、飞书项目/缺陷（feishu-project-collab）、日历/审批/多维表格（lark-*）。"
metadata:
  requires:
    bins: [curl, lark-cli]
    cliHelp: "lark-cli im --help"
---

# 飞书群聊协作 / 机器人（Feishu Chat Collab）

你具备在飞书群里完成「**读别人回复 → 分析怎么处理 → 拟一条回复 → 发送（能 @人、带链接）**」的能力。
这是一个**按需触发、无需实时值守**的闭环：用户喊你「看看群里在聊什么、帮我拟条回复发出去」时才跑。

能力拆成两条独立通道，各自的前置配置不同：

| 通道 | 干什么 | 靠什么 | 身份 |
|------|--------|--------|------|
| **A. 发消息（写）** | 往群里推文本/卡片，能 @人、带超链接 | 群「自定义机器人」Webhook + `curl` | 机器人（群内 bot） |
| **B. 读消息（读）** | 读自己所在群的历史消息、别人的回复 | `lark-cli`（背后是一个飞书应用） | 你本人（user 身份） |

> 两条通道的 `open_id`（`ou_xxx`）**不通用**：见「踩坑 · open_id 跨应用隔离」。@人时用的 id 必须来自发消息那一侧能识别的应用。

---

## 适用范围

| 适用 ✅ | 不适用 ❌ |
|---------|-----------|
| 读某个群的最新消息 / 别人的回复并分析 | 飞书云文档读写 → `feishu-doc-collab` |
| 往群里发文本 / interactive 卡片（@人、带链接） | 飞书项目 / 缺陷单 → `feishu-project-collab` |
| 「帮我拟一条群回复并发出去」的完整闭环 | 日历 / 会议 → `lark-calendar` |
| 机器人定时/按需向群播报 | 审批 → `lark-approval`；多维表格 → `lark-base` |

**Agent 路由判断**：用户意图是「群里 / 群消息 / 群回复 / 机器人往群发 / @群里某人」时命中本 skill；
涉及文档、项目工作项、日历时转交对应 skill。

---

## 前置配置

发消息和读消息是两套独立前置，按需要用到哪条通道再配哪条。每步都标注了「**可自动完成**」还是「**需与用户配合**」。

### A. 发消息前置（自定义机器人 Webhook）

**需与用户配合**（拿 webhook 这步 AI 做不了，要用户在飞书客户端操作）：

1. 在目标群里：群设置 → **群机器人 / 添加机器人** → 选「**自定义机器人**（Custom Bot / 通过 Webhook 接入）」。
2. 起个名字、加个头像，**记下生成的 Webhook 地址**，形如：
   `https://open.feishu.cn/open-apis/bot/v2/hook/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`
3. **安全设置**（三选一或组合，决定后续怎么发）：
   - **自定义关键词**：消息正文必须包含设定的关键词，否则被拒。→ 见「踩坑 · 关键词」。
   - **签名校验**：需用 secret 对时间戳算签名随请求带上。→ 见「发消息 · 签名校验」。
   - **IP 白名单**：只允许指定出口 IP 调用（自动化机器所在网络需在白名单内）。

**可自动完成**：拿到 webhook 后，把它存成环境变量或本地配置复用，避免每次粘贴、也避免写进命令历史/仓库：

```bash
# 存到当前 shell（临时）
export FEISHU_WEBHOOK="<WEBHOOK_URL>"
# 或写进本地不提交的文件（长期），用时 source
echo 'export FEISHU_WEBHOOK="<WEBHOOK_URL>"' >> ~/.feishu_chat.env
# 若开了签名校验，secret 一并存（切勿提交到仓库）
echo 'export FEISHU_WEBHOOK_SECRET="<SECRET>"' >> ~/.feishu_chat.env
```

> ⚠️ Webhook URL 本身就是凭证，任何人拿到都能往群里发消息。**不要提交到公开仓库、不要贴进聊天**。

### B. 读消息前置（lark-cli，user 身份）

**可自动完成**：确认 `lark-cli` 已安装、当前登录态。

```bash
lark-cli --version          # 确认已安装；未装则提示用户按其渠道安装
lark-cli auth status        # 看当前是否已登录、以什么身份
```

**需与用户配合**（扫码授权只能用户本人在手机飞书上确认；后台加 scope 也需用户/管理员操作）：

读群消息需要以下 **scope**（一个都不能少，原因见「踩坑 · scope 前置校验」）：

| scope | 作用 |
|-------|------|
| `im:chat:read` | 搜群、拿 `chat_id` |
| `im:message.group_msg:get_as_user` | 以用户身份读**群**消息 |
| `im:message.p2p_msg:get_as_user` | 以用户身份读**单聊**消息（读群也会被前置校验要求，绕不过） |
| `im:message.reactions:read` | 读表情回复（`chat-messages-list` 前置校验会一并要，加 `--no-reactions` 也绕不过） |

授权走 **device-flow（设备码）**，可照抄：

```bash
# 1) 发起授权，拿 device_code + 验证链接（--no-wait 不阻塞，便于把链接交给用户）
lark-cli auth login \
  --scope "im:chat:read im:message.group_msg:get_as_user im:message.p2p_msg:get_as_user im:message.reactions:read" \
  --no-wait --json
# 输出里取 verification_url（或 verification_uri_complete）和 device_code

# 2) 把链接给用户在飞书里确认；也可生成二维码图片让用户手机扫
lark-cli auth qrcode "<VERIFICATION_URL>" --output ./feishu_auth_qr.png
#   → 把 feishu_auth_qr.png 交给用户扫码

# 3) 用户确认后，用 device_code 收尾换取 token
lark-cli auth login --device-code "<DEVICE_CODE>"

# 4) 复核
lark-cli auth status
```

另外两个「人」层面的前置：
- **你本人必须在目标群里**（user 身份只能读自己可见的群）。
- 若某个 scope 报「应用未开通」，需到该 lark-cli 应用的开发者后台给应用加上对应权限后再授权（见「踩坑 · scope 前置校验」）。

---

## 通道 A：发消息（Webhook + 卡片）

### 为什么发卡片而不是纯文本

Webhook 直接发 markdown 文本**不会渲染**（`**加粗**`、链接都按原样显示）。
要富文本效果，发 **interactive 卡片**（`msg_type: interactive`），正文用 **`lark_md`** 元素。

`lark_md` 支持 / 不支持：

| 支持 ✅ | 不支持 ❌ |
|---------|-----------|
| `**加粗**` | 表格 |
| `[文本](https://...)` 超链接 | `#` / `##` 标题 |
| `\n` 换行 | 图片直接内联（需用卡片 image 组件） |
| `<at id=ou_xxx></at>` @某人 | 复杂 markdown 扩展 |

> **对比/清单不能用表格**，改成 `①②③` 或 `- ` 分点 + 加粗小标题。

### 最小可用：发纯文本（探活用）

```bash
curl -s -X POST "$FEISHU_WEBHOOK" \
  -H 'Content-Type: application/json' \
  --data '{"msg_type":"text","content":{"text":"hello from bot"}}'
# 返回 {"code":0,...} 即成功；非 0 看 msg 排查（常见：关键词不匹配 / 签名缺失）
```

### 推荐：发 interactive 卡片

把卡片 payload 写进文件再 `--data @file`，避免命令行转义地狱。骨架（可照抄改内容）：

```json
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "header": {
      "template": "blue",
      "title": { "tag": "plain_text", "content": "群回复 / 播报标题" }
    },
    "elements": [
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**结论**：xxx\n\n**依据**：\n① 第一点\n② 第二点\n\n详情见 [文档](https://example.com/doc)"
        }
      },
      { "tag": "hr" },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "<at id=ou_xxx></at> 麻烦看下 👀"
        }
      }
    ]
  }
}
```

发送：

```bash
# 假设上面存为 card.json
curl -s -X POST "$FEISHU_WEBHOOK" \
  -H 'Content-Type: application/json' \
  --data @card.json
```

- `header.template` 常用色：`blue` / `turquoise` / `green` / `yellow` / `orange` / `red` / `grey`。
- `title` 用 `plain_text`（标题不吃 markdown）；正文用 `lark_md`。
- 多段内容用多个 `{"tag":"div"}`，中间插 `{"tag":"hr"}` 分隔。

> 卡片结构与 @人写法的更多细节（多元素排布、颜色、常见报错）见 [`references/webhook-card.md`](references/webhook-card.md)。

### @人怎么写

- 在 `lark_md` 里用 `<at id=ou_xxx></at>`，`ou_xxx` 是**在发消息这一侧应用里有效的 open_id**。
- 自定义机器人没有「查用户」的能力，`ou_xxx` 通常来自：用户直接提供、或此前该侧已知的 id。
- ⚠️ **不要把 lark-cli（读消息侧）拿到的 `ou_` 直接塞进 webhook 卡片**——两侧应用不同，open_id 不通用，@ 会失效或指向错人。见「踩坑 · open_id 跨应用隔离」。
- `<at id=all></at>` 可 @所有人（若群和机器人允许）。

### 安全设置：关键词

若机器人开了「自定义关键词」，**消息正文必须包含该关键词**，否则返回类似 `key words not found`。
- 纯文本：把关键词写进 `content.text`。
- 卡片：把关键词写进某个 `lark_md` 的 `content` 里（哪怕放句尾）。

### 安全设置：签名校验

若开了签名校验，需用 secret 算签名随请求发送。算法：以 `timestamp + "\n" + secret` 为**密钥**、空串为**内容**做 HmacSHA256，再 base64。

```bash
TS=$(date +%s)
SIGN=$(printf '' | openssl dgst -sha256 -hmac "${TS}
${FEISHU_WEBHOOK_SECRET}" -binary | base64)
curl -s -X POST "$FEISHU_WEBHOOK" \
  -H 'Content-Type: application/json' \
  --data "{\"timestamp\":\"${TS}\",\"sign\":\"${SIGN}\",\"msg_type\":\"text\",\"content\":{\"text\":\"hello\"}}"
```

> `-hmac` 的 key 里那个换行是**字面 `\n`**（timestamp 与 secret 之间）。用上面 `"${TS}<换行>${SECRET}"` 的写法确保是真换行。签名错误返回 `sign match fail`，多半是时间戳过期（默认 1 小时有效）或 key 拼接顺序错。

---

## 通道 B：读消息（lark-cli，user 身份）

### 定位群 → 拿 chat_id

```bash
lark-cli im +chat-search --query "<GROUP_NAME>" --as user
# 返回里取目标群的 chat_id（形如 oc_xxx）
```

### 读群最新消息

```bash
lark-cli im +chat-messages-list --chat-id oc_xxx --order desc --as user
# --order desc：最新在前，方便只看最近几条
# 需要看更多用分页参数（--page-all / --page-limit，视 lark-cli 版本）
```

- 消息里带 `sender.name`（发送者显示名，无需额外通讯录权限）。
- 系统消息 `msg_type: system` 没有发送者名，正常现象。
- 想少一次表情查询可加 `--no-reactions`，但注意 scope 仍要 `im:message.reactions:read`（前置校验拦），见踩坑。

---

## 闭环：读群 → 分析 → 拟回复 → 发送

标准动作串起来：

```
1. 定位群         lark-cli im +chat-search --query "<GROUP_NAME>" --as user  → chat_id
2. 读最新消息     lark-cli im +chat-messages-list --chat-id oc_xxx --order desc --as user
3. 理解 + 分析    （你来读懂讨论、判断该怎么回、要 @谁、要不要带链接）
4. 拟回复         组织成 lark_md：结论/依据分点、超链接、@对方（ou_xxx 用发消息侧有效的 id）
5. 发送           curl POST $FEISHU_WEBHOOK --data @card.json（interactive 卡片）
6. 回执           返回 code:0 即发成功；非 0 按 msg 排查（关键词/签名/结构）
```

要点：
- **读写身份不同**：读是「你本人」，发是「群机器人」。群里会显示是机器人发的，不是你本人发的。
- **@人要拿对 id**：读到的对方 `ou_`（lark-cli 侧）不能直接用于卡片 @；@ 用的 id 需发消息侧能识别（用户提供或已知）。拿不到就用纯文字点名（如「@某某（人工核对）」）并向用户说明。
- **发前自检**：正文若走带关键词/签名的机器人，确认已满足；卡片 JSON 先本地校验合法（`python3 -m json.tool card.json`）。

---

## ⚠️ 踩坑经验（都是实测踩过的）

1. **Webhook 发 markdown 文本不渲染** → 必须发 `interactive` 卡片 + `lark_md`。且 `lark_md` **不支持表格和 `#` 标题**，对比信息改用 `①②③` 分点。

2. **scope 前置校验绑死一串**：`chat-messages-list` 即使只读群、即使加 `--no-reactions`，前置校验也会一并要求 `im:message.p2p_msg:get_as_user` 和 `im:message.reactions:read`。所以读群的 scope 要一次配齐这 4 个（见前置配置 B），少一个就跑不通。

3. **坑 20001「请求不合法」**：一次把多个 scope 捆一起申请可能报 `20001`，往往是**其中某个 scope 应用侧未开通**。定位办法：**逐个 / 分批申请**，缩小到具体是哪个 scope。确认是未开通的，就到该 lark-cli 应用的开发者后台给应用补上该权限，再重新授权。

4. **open_id 跨应用隔离**：`open_id`（`ou_xxx`）**按应用隔离**。在别的应用（比如另一个飞书 MCP）里拿到的 `ou_`，拿到 lark-cli 这个应用会报 `open_id cross app`；反过来，lark-cli 读到的 `ou_` 也不能直接用于自定义机器人卡片的 `<at id=...>`。**要用哪一侧，就用哪一侧自己的身份/搜索去拿对应 id**。

5. **读消息必须「你本人在群里」**：`--as user` 是用户身份，只能读你自己可见的群。不在群里就搜不到 / 读不到。

6. **凭证不外泄**：Webhook URL、签名 secret、lark-cli token 都是凭证。不提交仓库、不贴聊天；泄露后在群机器人设置里重建 webhook / 重置。

7. **卡片 JSON 转义**：直接把长 JSON 拼进 `--data '...'` 极易被 shell 转义搞坏。**一律写文件用 `--data @card.json`**，发前 `python3 -m json.tool card.json` 验证合法。

---

## 命令速查

| 目的 | 命令 |
|------|------|
| 探活发文本 | `curl -s -X POST "$FEISHU_WEBHOOK" -H 'Content-Type: application/json' --data '{"msg_type":"text","content":{"text":"..."}}'` |
| 发卡片 | `curl -s -X POST "$FEISHU_WEBHOOK" -H 'Content-Type: application/json' --data @card.json` |
| 校验卡片 JSON | `python3 -m json.tool card.json` |
| 登录态 | `lark-cli auth status` |
| 发起授权 | `lark-cli auth login --scope "<scopes>" --no-wait --json` |
| 生成授权二维码 | `lark-cli auth qrcode "<VERIFICATION_URL>" --output qr.png` |
| 授权收尾 | `lark-cli auth login --device-code "<DEVICE_CODE>"` |
| 搜群拿 chat_id | `lark-cli im +chat-search --query "<GROUP_NAME>" --as user` |
| 读群最新消息 | `lark-cli im +chat-messages-list --chat-id oc_xxx --order desc --as user` |

---

## 分工速览（可自动 vs 需配合）

| 事项 | 谁做 |
|------|------|
| 在群里加自定义机器人、拿 Webhook | **用户**（飞书客户端操作） |
| 决定/配置机器人安全设置（关键词/签名/IP） | **用户** |
| 把 webhook / secret 存环境变量复用 | **AI 可自动** |
| 拼卡片 payload、发消息、校验回执 | **AI 可自动** |
| `lark-cli` 安装 | 用户（按其安装渠道） |
| 发起 device-flow 授权、生成二维码 | **AI 可自动** |
| 手机飞书扫码 / 确认授权 | **用户本人** |
| 开发者后台给应用补 scope（20001 时） | **用户 / 管理员** |
| 搜群、读消息、分析、拟稿 | **AI 可自动** |
