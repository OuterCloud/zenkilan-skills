---
name: feishu-doc-collab
version: 1.1.0
description: "飞书文档协作：通过飞书云文档与团队成员进行异步协作（环境检测、配置引导、文档读写、评论、搜索）。当用户需要通过飞书文档和他人协作、读取或更新飞书文档、添加评论或搜索文档时使用。不负责：飞书消息收发（lark-im）、日历（lark-calendar）、审批（lark-approval）、多维表格（lark-base）。"
metadata:
  requires:
    bins: []
---

# 飞书文档协作

你具备通过飞书 MCP 工具读写飞书云文档的能力。当用户需要通过飞书文档与团队协作时，按照本规则执行。

## 适用范围

| 适用 ✅ | 不适用 ❌ |
|---------|-----------|
| 飞书云文档（docx）读写 | 飞书消息收发 → `lark-im` |
| 飞书知识库（wiki）读写 | 日历/会议 → `lark-calendar` |
| 文档评论、@ 人 | 审批流程 → `lark-approval` |
| 文档搜索 | 多维表格/Base → `lark-base` |
| 文档创建（含知识库、文件夹） | 电子表格 → `lark-sheets` |
| 子文档列表查询 | 文件上传/下载 → `lark-drive` |

Agent 路由判断：用户意图涉及文档读写/评论/搜索时命中本 skill；涉及消息、日历、审批、表格等其他飞书能力时转交对应 skill。

---

## 环境检测

每次触发飞书文档相关意图时，先确认飞书 MCP 工具可用：

1. 尝试调用 `search-doc` 或 `fetch-doc` 工具
2. 若工具可用且返回正常 → 进入对应协作场景
3. 若工具不可用（找不到工具） → 输出 MCP 配置引导后停止（见下方）
4. 若工具可用但返回认证/权限错误（如 `token expired`、`unauthorized`、`permission denied`、`invalid_grant`、HTTP 401/403 等） → 输出授权过期引导后停止

### 工具不可用 — MCP 未配置

```
飞书 MCP 未配置。请完成以下步骤：

1. 创建飞书 MCP 服务：
   打开 https://open.feishu.cn/page/mcp/
   → 点击「创建 MCP 服务」
   → 填写名称，勾选云文档相关权限
   → 创建完成后复制 MCP 端点 URL

2. 将以下内容写入你的 MCP 配置文件：

   {
     "mcpServers": {
       "feishu": {
         "url": "<你的飞书 MCP 端点 URL>"
       }
     }
   }

   配置文件位置：
   • Kiro:       ~/.kiro/settings/mcp.json
   • Claude Code: ~/.claude.json
   • Cursor:     .cursor/mcp.json
   • Windsurf:   ~/.codeium/windsurf/mcp_config.json

3. 重启工具使配置生效，然后重试。
```

### 工具可用但授权过期

当飞书 MCP 工具调用返回认证相关错误时，输出以下引导：

```
飞书授权已过期，需要重新授权。请按以下步骤操作：

1. 打开飞书 MCP 管理页面：
   https://open.feishu.cn/page/mcp/

2. 找到你正在使用的 MCP 服务 → 点击进入

3. 点击「重新授权」或检查授权状态
   • 确认云文档相关权限已勾选（文档读写、搜索、评论等）
   • 完成授权确认

4. 授权完成后直接重试即可，无需重启。

若反复出现授权问题，可尝试：
• 删除该 MCP 服务后重新创建
• 检查飞书管理后台是否限制了应用权限
```

---

## 协作场景

### 场景 1: 读取文档

**触发词**：用户提供飞书文档 URL、说"看下文档"、"读一下"、"同步最新内容"。

**流程**：
1. 从 URL 或上下文中获取 `doc_id`
2. 调用 `fetch-doc` 读取 Markdown 内容
3. 文档过长时用 `limit` + `offset` 分页
4. 按用户需求展示或提取信息

**飞书文档 URL 格式**：
- `https://*.feishu.cn/docx/<token>` — 标准飞书域名
- `https://<企业自定义域名>.feishu.cn/docx/<token>` — 企业自定义域名（如 `mycompany.feishu.cn`）
- `https://*.feishu.cn/wiki/<token>` — 知识库文档
- 直接传 token 也可

> **注意**：企业可能使用自定义子域名（如 `https://mycompany.feishu.cn/docx/xxx`），只要路径匹配 `/docx/<token>` 或 `/wiki/<token>` 格式即视为有效飞书文档 URL，不要因域名前缀不是 `open` 或 `www` 就判定无效。

### 场景 2: 更新文档

**触发词**："更新文档"、"写到文档里"、"追加"、"改一下文档中的 xxx"。

**流程**：
1. 先 `fetch-doc` 获取当前内容（避免覆盖他人修改）
2. 选择更新模式（见「工具速查」的使用限制列）
3. 调用 `update-doc` 执行
4. 确认结果

**原则**：优先小粒度更新，避免 overwrite 破坏协作内容和评论。

### 场景 3: 创建文档

**触发词**："创建文档"、"新建"、"帮我写一份 xxx"。

**流程**：
1. 确认标题和存放位置：
   - 知识库节点 → `wiki_node`
   - 知识空间 → `wiki_space`
   - 文件夹 → `folder_token`
   - 都没指定 → 个人空间
2. 组织 Markdown 内容（利用飞书扩展语法：callout、grid、mermaid 等）
3. 调用 `create-doc`
4. 返回文档链接

### 场景 4: 评论与 @ 人

**触发词**："加评论"、"@ 某人"、"提醒他看一下"。

**流程**：
1. 确认评论内容
2. 如需 @ 人 → 调用 `search-user` 获取 `open_id`
3. 构建 elements 数组（type: text / mention / link）
4. 调用 `add-comments`

### 场景 5: 搜索文档

**触发词**："找一下 xxx"、"搜索文档"、"最近的文档"。

**流程**：
1. 构建搜索条件（关键词、时间、作者）
2. 调用 `search-doc`
3. 展示结果列表（标题 + URL + 时间）
4. 用户选择后进入读取或更新

### 场景 6: 查看评论

**触发词**："看评论"、"有什么反馈"、"别人怎么说的"。

**流程**：
1. 调用 `get-comments` 获取评论
2. 按时间整理展示
3. 用户可回复或采取行动

---

## 工具速查

| 工具 | 用途 | 关键参数 | 使用限制 |
|------|------|---------|----------|
| `fetch-doc` | 读取文档 | `doc_id` | — |
| `create-doc` | 创建文档 | `title`, `markdown`, 位置参数 | — |
| `update-doc` | 更新文档 | `doc_id`, `mode`, `markdown` | `overwrite` 模式 ⚠️ 需用户明确确认（会丢失评论和协作历史） |
| `add-comments` | 添加评论 | `doc_id`, `elements[]` | — |
| `get-comments` | 获取评论 | `doc_id` | — |
| `search-doc` | 搜索文档 | `query`, `filters` | — |
| `search-user` | 搜索用户 | `query` | — |
| `list-docs` | 列子文档 | `doc_id` | — |
| `get-user` | 获取用户信息 | `open_id`（可选） | — |

---

## 更新策略

| 操作 | 模式 | 说明 |
|------|------|------|
| 追加新内容 | `append` | 最安全，不影响已有内容 |
| 替换某章节 | `replace_range` + `selection_by_title` | 按标题定位整章替换 |
| 改一句话/一段 | `replace_range` + `selection_with_ellipsis` | 精确定位替换 |
| 在某处插入 | `insert_after` / `insert_before` | 不破坏上下文 |
| 全文重建 | `overwrite` | ⚠️ **需用户确认**：会丢失评论、协作历史、图片引用 |

---

## 协作最佳实践

- **更新前先读取**：每次修改前 `fetch-doc` 拿最新内容，避免覆盖他人改动
- **最小粒度更新**：用 replace_range / insert 而非 overwrite
- **结构化协作文档**：待办表格 + 状态列 + 变更记录，各方直接改状态
- **变更留痕**：更新后在「变更记录」追加一行说明改了什么
- **并发冲突处理**：若 `update-doc` 返回冲突错误（如内容已变更），重新 `fetch-doc` 获取最新内容后再次尝试更新；若用户与他人同时编辑同一章节，提示用户确认是否覆盖或手动合并
