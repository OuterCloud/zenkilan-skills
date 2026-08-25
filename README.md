# zenkilan-skills

个人沉淀的 AI 编码 Agent 自定义 Skills 合集。适用于 Kiro CLI、Claude Code、Cursor、Windsurf、Aider 等支持自定义指令的工具。

## Skills

| Skill | 说明 |
|-------|------|
| [web-probe](./web-probe/) | 前端自动化验证：用本机 Chrome 打开指定 URL，按需截图、抓网络请求（HAR/JSON）、收集 console 日志 |
| [feishu-doc-collab](./feishu-doc-collab/) | 飞书文档协作：通过飞书云文档与团队成员进行异步协作（环境检测、配置引导、文档读写、评论、搜索） |
| [generate-agents-md](./generate-agents-md/) | 为 git 项目生成或更新 AGENTS.md（面向 AI 编码 agent 的项目说明） |
| [sync-mr](./sync-mr/) | 代码变更后的标准 MR 同步流程：更新测试文档、amend commit + force push、更新 MR 描述 |
| [pptx-gen](./pptx-gen/) | 基于模板生成专业 PPT：分析模板结构、规划内容映射、自动填充生成 |

## 使用方式

这些 skill 的核心内容是 **SKILL.md**（纯 Markdown prompt），不依赖特定工具的私有能力，可适配任何支持自定义指令的 AI 编码工具。

### Kiro CLI / Kiro IDE

将 skill 目录软链到 `~/.kiro/skills/`：

```bash
ln -s $(pwd)/web-probe ~/.kiro/skills/web-probe
ln -s $(pwd)/feishu-doc-collab ~/.kiro/skills/feishu-doc-collab
ln -s $(pwd)/generate-agents-md ~/.kiro/skills/generate-agents-md
ln -s $(pwd)/sync-mr ~/.kiro/skills/sync-mr
ln -s $(pwd)/pptx-gen ~/.kiro/skills/pptx-gen
```

### Claude Code

将 SKILL.md 内容引入 Claude Code 的指令系统：

```bash
# 方式一：全局（所有项目生效）
# 在 ~/.claude/commands/ 下创建命令文件
mkdir -p ~/.claude/commands
cp web-probe/SKILL.md ~/.claude/commands/web-probe.md
cp generate-agents-md/SKILL.md ~/.claude/commands/generate-agents-md.md
cp sync-mr/SKILL.md ~/.claude/commands/sync-mr.md

# 方式二：项目级（在项目根目录）
# 放入 .claude/commands/ 下作为斜杠命令
mkdir -p .claude/commands
cp /path/to/zenkilan-skills/sync-mr/SKILL.md .claude/commands/sync-mr.md
```

也可以在 `CLAUDE.md` 中用一行引用：

```markdown
对于代码提交流程，参考 /path/to/zenkilan-skills/sync-mr/SKILL.md
```

> **注意**：SKILL.md 顶部的 YAML frontmatter（`---` 包裹的元数据）是 Kiro 格式，Claude Code 会忽略它，不影响使用。

### Cursor

放入 `.cursor/rules/` 目录，将 frontmatter 改为 MDC 格式：

```bash
mkdir -p .cursor/rules

# 复制并替换 frontmatter
for skill in web-probe generate-agents-md sync-mr feishu-doc-collab; do
  # 去掉 Kiro frontmatter，加 Cursor frontmatter
  sed '1,/^---$/{ /^---$/!d; }' /path/to/zenkilan-skills/$skill/SKILL.md | \
    sed '1s/^---$/---\ndescription: "'$skill'"\nglobs:\nalwaysApply: false\n---/' \
    > .cursor/rules/$skill.mdc
done
```

或手动复制 SKILL.md 内容，在顶部替换为：

```yaml
---
description: "skill 的描述"
globs:
alwaysApply: false
---
```

### Windsurf

在 Windsurf 设置 → Rules 中，直接粘贴 SKILL.md 的正文内容（去掉 frontmatter）。

### Aider

在 `.aider.conf.yml` 中引用：

```yaml
read:
  - /path/to/zenkilan-skills/generate-agents-md/SKILL.md
  - /path/to/zenkilan-skills/sync-mr/SKILL.md
```

### 其他工具

只要 AI 编码工具支持「自定义系统指令」或「读取额外文件作为上下文」，都可以直接使用 SKILL.md 的正文部分。YAML frontmatter 是可选元数据，去掉不影响功能。

## 依赖说明

| Skill | 额外依赖 |
|-------|---------|
| web-probe | Node.js + `npm install`（安装 playwright-core） |
| feishu-doc-collab | 飞书 MCP 端点（[配置方式](./feishu-doc-collab/README.md)） |
| generate-agents-md | 无 |
| sync-mr | `glab` CLI（GitLab MR 操作） |
| pptx-gen | Python 3 + `lxml` + `PyMuPDF`；Keynote（macOS）或 LibreOffice（视觉 QA）；Node.js + PptxGenJS 仅用于用户明确无模板时的可选自由设计回退 |

## 许可

MIT — 随便用，不需要署名。
