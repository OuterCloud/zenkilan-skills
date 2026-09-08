# Webhook 卡片 payload 参考（自定义机器人 / interactive）

自定义机器人 Webhook 发 interactive 卡片的完整结构、`lark_md` 用法、@人写法、常见报错。
主流程见 [`../SKILL.md`](../SKILL.md) 的「通道 A：发消息」。

---

## 顶层结构

```json
{
  "msg_type": "interactive",
  "card": {
    "config":   { ... },
    "header":   { ... },
    "elements": [ ... ]
  }
}
```

- `msg_type` 固定 `"interactive"`。
- `card.config` / `card.header` 可选；`card.elements` 是正文，必填。

---

## config

```json
"config": { "wide_screen_mode": true }
```

- `wide_screen_mode: true`：宽屏自适应，长内容更好看。基本每次都开。

---

## header

```json
"header": {
  "template": "blue",
  "title": { "tag": "plain_text", "content": "标题文字" }
}
```

- `title` 用 **`plain_text`**（标题不解析 markdown）。
- `template` 是标题栏底色，常用值：

| 值 | 语义建议 |
|----|----------|
| `blue` | 普通通知 / 播报 |
| `turquoise` | 信息 |
| `green` | 成功 / 完成 |
| `yellow` / `orange` | 提醒 / 警告 |
| `red` | 失败 / 风险 |
| `grey` | 弱化 / 归档 |

不需要标题栏时整个 `header` 可省略。

---

## elements（正文）

正文是数组，按顺序渲染。常用三种 tag：

### 1. div + lark_md（文本，最常用）

```json
{
  "tag": "div",
  "text": {
    "tag": "lark_md",
    "content": "**结论**：xxx\n\n**依据**：\n① 第一点\n② 第二点\n\n参见 [文档](https://example.com)"
  }
}
```

`lark_md` 能力边界：

| 支持 ✅ | 不支持 ❌ |
|---------|-----------|
| `**加粗**` | 表格（用 `①②③` 或 `- ` 分点代替） |
| `[文本](https://...)` 超链接 | `#` / `##` 标题（用 `**加粗**` 当小标题） |
| `\n` 换行、`\n\n` 空行分段 | 图片内联（要图片用独立 image 组件 + image_key） |
| `<at id=ou_xxx></at>` @人 | 大部分 markdown 扩展语法 |

### 2. hr（分隔线）

```json
{ "tag": "hr" }
```

### 3. note（弱化脚注，可选）

```json
{
  "tag": "note",
  "elements": [
    { "tag": "lark_md", "content": "由机器人自动发送 · 如需人工核对请回复本群" }
  ]
}
```

---

## @人写法

在任意 `lark_md` 的 `content` 里内联：

```
<at id=ou_xxx></at> 麻烦看下
```

- `ou_xxx`：**在发消息这一侧应用里有效的 open_id**。
- `<at id=all></at>`：@所有人（群与机器人允许时）。
- ⚠️ 不要把 lark-cli（读消息侧）拿到的 `ou_` 直接用在这里 —— open_id 跨应用隔离，会失效或指向错人。拿不到发消息侧的 id 时，退化为纯文字点名并告知用户。

---

## 完整示例：一条群回复卡片

```json
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "header": {
      "template": "blue",
      "title": { "tag": "plain_text", "content": "关于 xxx 的回复" }
    },
    "elements": [
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**结论**：建议按方案 B 推进。\n\n**理由**：\n① 改动范围小，风险可控\n② 与现有流程兼容\n③ 可当天上线验证"
        }
      },
      { "tag": "hr" },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "细节见 [设计文档](https://example.com/design)\n\n<at id=ou_xxx></at> 你看这样可以吗？"
        }
      },
      {
        "tag": "note",
        "elements": [
          { "tag": "lark_md", "content": "由机器人自动发送" }
        ]
      }
    ]
  }
}
```

发送：

```bash
python3 -m json.tool card.json >/dev/null && \
curl -s -X POST "$FEISHU_WEBHOOK" -H 'Content-Type: application/json' --data @card.json
```

---

## 常见报错

| 返回 msg / 现象 | 原因 | 处理 |
|-----------------|------|------|
| `code != 0`，`key words not found` | 机器人开了自定义关键词，正文没含关键词 | 把关键词写进某个 `lark_md` 或 `content.text` |
| `sign match fail` | 开了签名校验，签名缺失/错误/过期 | 按 SKILL.md「签名校验」重算，注意时间戳 1 小时有效、key 是 `timestamp\nsecret` |
| 文本原样显示 `**` `[]()` 不渲染 | 用了 `msg_type: text` 发 markdown | 改发 `interactive` 卡片 + `lark_md` |
| 表格 / `#` 标题不显示 | `lark_md` 不支持 | 表格改分点、标题改 `**加粗**` |
| @ 不生效 / @错人 | 用了别的应用的 `ou_` | 用发消息侧有效的 open_id；拿不到就纯文字点名 |
| `curl` 报 JSON 解析失败 | payload 被 shell 转义搞坏 | 写文件用 `--data @card.json`，先 `python3 -m json.tool` 校验 |
