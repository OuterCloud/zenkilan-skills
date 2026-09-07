# 飞书项目协作 Skill（Feishu Project / Meego）

通过**飞书项目 MCP**（Meego MCP Server）查询与流转研发工作项，形成「缺陷发现 → 处理 → 修复回填 → 流转解决」的自闭环。适用于所有支持 MCP 的 AI 编码工具。

## 这是什么

一个 **prompt 文件（SKILL.md）+ MCP 配置说明**，让你的 AI 编码助手（Kiro / Claude Code / Cursor / Windsurf 等）获得**飞书项目**（`project.feishu.cn`，内部代号 Meego）读写能力，用于：

- 缺陷单闭环：AI 查缺陷 → 定位修复 → 回填 MR 链接 → 流转到已解决
- 需求 / 任务查询与状态驱动
- 排期 / 计划表(WBS) / 视图查询
- 任何围绕飞书项目工作项的协作

> ⚠️ **飞书项目 ≠ 飞书开放平台**。这俩 MCP 完全不同：
> - 飞书**文档/IM/表格** → `feishu-doc-collab` / `lark-*`（连 `mcp.feishu.cn` / `open.feishu.cn`）
> - 飞书**项目工作项/缺陷** → 本 skill（连 `project.feishu.cn/mcp_server/v1`）

## 前置条件

飞书项目 MCP 是**空间级内置能力，无需自建插件**。拿到 Token 即可：

1. 打开飞书项目 → 左侧「更多」→「MCP 配置」
2. 打开「MCP Server」开关
3. 「数据授权范围」勾选：✅ 允许查看数据信息　✅ 允许创建或修改数据信息
4. 「连接 MCP」选 **HTTP Header** tab →「复制 Token」（形如 `m-xxxxxxxx-xxxx-xxxx-...`）

> ⚠️ Token 是密钥，不要提交到公开仓库。失效时在同页「重置 Token」。

三种连接方式：
- **HTTP Header（推荐）**：URL + `X-Mcp-Token` 头，适合固定自动化身份。
- **HTTP OAuth**：同一 URL，一键浏览器授权，无需 token。
- **Stdio**：`npx -y @lark-project/meegle@latest install`（顺带装 Meegle CLI + Agent Skill）。

传输协议为 **Streamable HTTP**。

## 安装配置

### Step 1: 配置飞书项目 MCP Server

**注意 header 名是 `X-Mcp-Token`，不是 `Authorization: Bearer`**：

```json
{
  "mcpServers": {
    "feishu-project": {
      "url": "https://project.feishu.cn/mcp_server/v1",
      "headers": { "X-Mcp-Token": "<你的 Token>" }
    }
  }
}
```

（若用 OAuth 方式，去掉 `headers`，只留 `url`，首次连接走浏览器授权。）

写入对应工具的 MCP 配置文件：

| 工具 | 配置文件路径 | 作用域 |
|------|------------|--------|
| **Kiro IDE / CLI** | `.kiro/settings/mcp.json`（项目级）<br>`~/.kiro/settings/mcp.json`（用户级） | 项目 / 全局 |
| **Claude Code** | `.mcp.json`（项目根）<br>`~/.claude.json`（用户级） | 项目 / 全局 |
| **Cursor** | `.cursor/mcp.json` | 项目 |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | 全局 |

> 💡 可与飞书文档 MCP（`feishu` / `mcp.feishu.cn`）并存，二者是不同 server，互不影响。推荐配在**用户级**（全局）。

### Step 2: 注入协作 Prompt

将 `SKILL.md` 放到对应工具能识别的自定义指令位置：

| 工具 | 放置位置 | 说明 |
|------|---------|------|
| **Kiro IDE / CLI** | 作为 skill 被 `resources: ["skill://..."]` 引用，或放 `.kiro/steering/` | 加 YAML frontmatter |
| **Claude Code** | 追加到 `CLAUDE.md` 或独立文件引用 | — |
| **Cursor** | `.cursor/rules/feishu-project-collab.mdc` | 加 MDC frontmatter |
| **Windsurf** | 粘贴到 Windsurf Rules | 手动粘贴 |

#### Kiro steering frontmatter（若放 steering）
```yaml
---
description: 飞书项目协作工作流，用于查询与流转研发工作项/缺陷单
inclusion: manual
---
```

#### Cursor MDC frontmatter
```yaml
---
description: 飞书项目协作工作流，用于查询与流转研发工作项/缺陷单
globs:
alwaysApply: false
---
```

### Step 3: 验证

在 AI 助手中输入：「查一下 XX 空间下我的缺陷列表」。

若返回工作项数据即配置成功。报错时排查：
1. MCP 配置路径 / header 名（必须 `X-Mcp-Token`）是否正确；
2. Token 是否有效（可用 SKILL.md「调试：用 curl 直连验证」一节 curl `initialize`，返回 `Meego MCP Server` 即有效）；
3. 是否重启 / 热重载生效；
4. 该 Token 对应用户是否在目标空间有权限、授权范围是否勾选。

## 关键经验（详见 SKILL.md「踩坑经验」）

- **MQL 字段名用该空间实际 label**：先 `list_workitem_field_config`（参数是 `work_item_type`）。缺陷常见：标题→`缺陷名称`、状态→`缺陷状态`、创建人→`创建者`、负责人→`当前负责人`。
- **MQL 用户值不能用 `current_login_user()`**：先 `search_user_info` 拿 userKey/显示名，再用 `'显示名'` 或 `'<id:userKey>'`。
- **缺陷是状态流**：`get_transitable_states` → `transition_state`；节点流用 `transition_node`。
- **无需自建插件**：这是空间级内置 MCP。

## 文件说明

```
feishu-project-collab/
├── README.md    # 本文件（安装配置说明）
└── SKILL.md     # 核心 prompt（工具无关，含场景/工具速查/踩坑经验/闭环/调试）
```

## 许可

随便用，不需要署名。
