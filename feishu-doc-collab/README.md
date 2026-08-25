# 飞书文档协作 Skill（通用版）

通过飞书云文档与团队成员进行异步协作。适用于所有支持 MCP 的 AI 编码工具。

## 这是什么

一个 **prompt 文件 + MCP 配置说明**，让你的 AI 编码助手（Kiro / Claude Code / Cursor / Windsurf 等）获得飞书文档读写能力，用于：

- 前后端协议文档对齐
- 技术方案异步评审
- 需求文档同步维护
- 任何需要通过飞书文档协作的场景

## 前置条件

需要一个飞书 MCP 端点 URL。获取方式：

1. 打开 [飞书 MCP 服务管理页面](https://open.feishu.cn/page/mcp/)
2. 点击「创建 MCP 服务」
3. 填写服务名称（如"我的文档助手"），勾选需要的能力（建议全选文档相关权限：云文档读写、搜索、评论等）
4. 创建完成后，复制生成的 MCP 端点 URL（形如 `https://mcp.feishu.cn/mcp/mcp_xxxxx`）

> ⚠️ 端点 URL 包含鉴权信息，不要提交到公开仓库。

## 安装配置

### Step 1: 配置飞书 MCP Server

所有工具的 MCP 配置格式相同，只是文件路径不同：

```json
{
  "mcpServers": {
    "feishu": {
      "url": "https://mcp.feishu.cn/mcp/<你的 MCP token>"
    }
  }
}
```

把上面的 JSON 写入对应工具的 MCP 配置文件：

| 工具 | 配置文件路径 | 作用域 |
|------|------------|--------|
| **Kiro IDE / CLI** | `.kiro/settings/mcp.json`（项目级）<br>`~/.kiro/settings/mcp.json`（用户级） | 项目 / 全局 |
| **Claude Code** | `.mcp.json`（项目根目录）<br>`~/.claude.json`（用户级） | 项目 / 全局 |
| **Cursor** | `.cursor/mcp.json` | 项目 |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | 全局 |

> 💡 推荐配置在**用户级**（全局），这样所有项目都能用。

### Step 2: 注入协作 Prompt

将 `feishu-doc-collab.md` 放到对应工具能识别的自定义指令位置：

| 工具 | 放置位置 | 说明 |
|------|---------|------|
| **Kiro IDE / CLI** | `.kiro/steering/feishu-doc-collab.md` | 加 YAML frontmatter（见下方） |
| **Claude Code** | 追加到 `CLAUDE.md` 或新建独立文件 | 直接引用 |
| **Cursor** | `.cursor/rules/feishu-doc-collab.mdc` | 加 MDC frontmatter（见下方） |
| **Windsurf** | 粘贴到 Windsurf Rules 设置中 | 手动粘贴 |

#### Kiro 格式（加 steering frontmatter）

在文件顶部添加：
```yaml
---
description: 飞书文档协作工作流，用于通过飞书云文档进行团队异步协作
inclusion: manual
---
```

#### Cursor 格式（MDC frontmatter）

在文件顶部添加：
```yaml
---
description: 飞书文档协作工作流，用于通过飞书云文档进行团队异步协作
globs:
alwaysApply: false
---
```

### Step 3: 验证

在 AI 助手中输入：「帮我搜索一下飞书文档」

如果返回了搜索结果，说明配置成功。如果报错工具不可用，检查：
1. MCP 配置文件路径是否正确
2. URL 是否完整（包含 token）
3. 是否重启了工具使配置生效

## 文件说明

```
feishu-doc-collab/
├── README.md                  # 本文件（安装配置说明）
└── feishu-doc-collab.md       # 核心 prompt（工具无关的纯 Markdown）
```

## 许可

随便用，不需要署名。
