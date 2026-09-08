# 飞书群聊协作 Skill（机器人版）

让 AI 在飞书群里完成「**读别人回复 → 分析 → 拟回复 → 发送（能 @人、带链接）**」的闭环。按需触发，无需实时值守。

## 这是什么

一个 **prompt 文件 + 两条通道的配置说明**，让你的 AI 编码助手（Kiro / Claude Code / Cursor / Windsurf 等）获得飞书群消息的读写能力，用于：

- 把群里的最新讨论读出来做分析、总结
- 拟一条群回复并直接发出去（富文本卡片、@人、带超链接）
- 机器人按需向群播报（发布通知、构建结果、值班提醒等）

能力拆成两条**互相独立**的通道，前置配置不同、身份也不同：

| 通道 | 干什么 | 靠什么 | 身份 |
|------|--------|--------|------|
| **A. 发消息（写）** | 往群里推文本 / interactive 卡片 | 群「自定义机器人」Webhook + `curl` | 机器人（群内 bot） |
| **B. 读消息（读）** | 读自己所在群的历史消息、别人的回复 | `lark-cli` | 你本人（user 身份） |

> ⚠️ 两条通道背后是**不同的应用**，`open_id`（`ou_xxx`）**不通用**。读消息侧拿到的 `ou_` 不能直接用于卡片 `<at id=...>`，详见 SKILL.md 的「踩坑 · open_id 跨应用隔离」。

只用其中一条通道也完全可以：只想让机器人往群里播报 → 只配 A；只想读群消息做分析 → 只配 B。

## 前置条件

### 通道 A：自定义机器人 Webhook（发消息）

需要用户在飞书客户端操作，AI 代劳不了：

1. 在目标群里：群设置 → **群机器人 / 添加机器人** → 选「**自定义机器人**（通过 Webhook 接入）」
2. 起名字、加头像，**记下生成的 Webhook 地址**，形如 `https://open.feishu.cn/open-apis/bot/v2/hook/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`
3. 按需配置**安全设置**（自定义关键词 / 签名校验 / IP 白名单）——选了哪种会影响发送方式，SKILL.md 里都有对应写法

> ⚠️ Webhook URL 本身就是凭证，任何人拿到都能往群里发消息。不要提交到公开仓库、不要贴进聊天。泄露后在群机器人设置里重建。

拿到后存成环境变量复用：

```bash
export FEISHU_WEBHOOK="<WEBHOOK_URL>"
# 若开了签名校验
export FEISHU_WEBHOOK_SECRET="<SECRET>"
```

### 通道 B：lark-cli（读消息）

需要已安装 [`lark-cli`](https://open.feishu.cn/) 并完成 user 身份授权，且**你本人必须在目标群里**（user 身份只能读自己可见的群）。

读群消息需要 4 个 scope，**一个都不能少**（`chat-messages-list` 的前置校验会绑死这一串）：

```
im:chat:read
im:message.group_msg:get_as_user
im:message.p2p_msg:get_as_user
im:message.reactions:read
```

授权走 device-flow，AI 可以自动发起并生成二维码，但**扫码确认必须用户本人在手机飞书上完成**：

```bash
lark-cli auth status   # 先看当前登录态
lark-cli auth login --scope "im:chat:read im:message.group_msg:get_as_user im:message.p2p_msg:get_as_user im:message.reactions:read" --no-wait --json
```

完整授权步骤见 SKILL.md 的「前置配置 B」。

## 安装配置

### Kiro CLI / Kiro IDE

```bash
ln -s $(pwd)/skills/feishu-chat-collab ~/.kiro/skills/feishu-chat-collab
```

### 通过 Lola（推荐）

```bash
lola install zenkilan-skills -a claude-code   # 或 cursor / copilot-cli / opencode
```

### Claude Code（手动）

```bash
mkdir -p .claude/commands
cp skills/feishu-chat-collab/SKILL.md .claude/commands/feishu-chat-collab.md
```

### Cursor

```bash
mkdir -p .cursor/rules
sed '1,/^---$/{ /^---$/!d; }' skills/feishu-chat-collab/SKILL.md | \
  sed '1s/^---$/---\ndescription: "feishu-chat-collab"\nglobs:\nalwaysApply: false\n---/' \
  > .cursor/rules/feishu-chat-collab.mdc
```

### Windsurf

在设置 → Rules 中粘贴 SKILL.md 的正文内容（去掉 YAML frontmatter）。

## 验证

配好通道 A 后，让 AI 发一条探活消息：

```bash
curl -s -X POST "$FEISHU_WEBHOOK" \
  -H 'Content-Type: application/json' \
  --data '{"msg_type":"text","content":{"text":"hello from bot"}}'
```

返回 `{"code":0,...}` 即成功。非 0 时看 `msg`：常见是关键词不匹配（`key words not found`）或签名缺失（`sign match fail`）。

配好通道 B 后，在 AI 助手中输入：「搜一下『<群名>』这个群，读最近 10 条消息」。能返回消息列表即成功。

## 依赖

| 依赖 | 用途 | 必需性 |
|------|------|--------|
| `curl` | 调用 Webhook 发消息 | 通道 A 必需 |
| `lark-cli` | 以 user 身份读群消息 | 通道 B 必需 |
| `python3` | `python3 -m json.tool` 校验卡片 JSON | 可选（推荐） |

## 文件说明

```
feishu-chat-collab/
├── README.md                    # 本文件（安装配置说明）
├── SKILL.md                     # 核心 prompt（前置配置、两条通道、闭环、踩坑、命令速查）
└── references/
    └── webhook-card.md          # 卡片 payload 参考（结构、lark_md 边界、@人、常见报错）
```

## 相关 Skill

- [feishu-doc-collab](../feishu-doc-collab/) — 飞书云文档协作（文档读写、评论、搜索）

## 许可

MIT — 随便用，不需要署名。
