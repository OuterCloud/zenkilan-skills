# zenkilan-skills

个人沉淀的 AI 编码 Agent 自定义 Skills 合集。适用于 Kiro CLI、Claude Code、Cursor、Windsurf、Aider 等支持自定义指令的工具。

## Skills

| Skill | 说明 |
|-------|------|
| [web-probe](./skills/web-probe/) | 前端自动化验证：用本机 Chrome 打开指定 URL，按需截图、抓网络请求（HAR/JSON）、收集 console 日志 |
| [feishu-doc-collab](./skills/feishu-doc-collab/) | 飞书文档协作：通过飞书云文档与团队成员进行异步协作（环境检测、配置引导、文档读写、评论、搜索） |
| [generate-agents-md](./skills/generate-agents-md/) | 为 git 项目生成或更新 AGENTS.md（面向 AI 编码 agent 的项目说明） |
| [sync-mr](./skills/sync-mr/) | 代码变更后的标准 MR 同步流程：更新测试文档、amend commit + force push、更新 MR 描述 |
| [pptx-gen](./skills/pptx-gen/) | 基于模板生成专业 PPT：分析模板结构、规划内容映射、自动填充生成 |

## 一键安装

### 推荐：通过 Lola（AI 上下文包管理器）

[Lola](https://github.com/LobsterTrap/lola) 是通用的 AI Skills 包管理器，一条命令安装到任意支持的 AI 工具。

```bash
# 1. 安装 Lola
uv tool install lola-ai   # 或 pip install lola-ai

# 2. 注册 marketplace
lola market add zenkilan https://raw.githubusercontent.com/zenkilan/zenkilan-skills/main/lola-market.yml

# 3. 安装全部 skills（选择目标工具）
lola install zenkilan-skills -a claude-code   # Claude Code
lola install zenkilan-skills -a cursor        # Cursor
lola install zenkilan-skills -a copilot-cli   # GitHub Copilot CLI
lola install zenkilan-skills -a opencode      # OpenCode

# 全局安装（所有项目生效）
lola install zenkilan-skills -a claude-code --scope user
```

### Claude Code（直接从 Git 安装）

```bash
# 项目级安装（在项目根目录执行）
lola mod add https://github.com/zenkilan/zenkilan-skills.git
lola install zenkilan-skills -a claude-code

# 或手动：将 SKILL.md 作为斜杠命令
mkdir -p .claude/commands
cp skills/web-probe/SKILL.md .claude/commands/web-probe.md
cp skills/sync-mr/SKILL.md .claude/commands/sync-mr.md
```

### Kiro CLI / Kiro IDE

```bash
# 软链到 ~/.kiro/skills/
ln -s $(pwd)/skills/web-probe ~/.kiro/skills/web-probe
ln -s $(pwd)/skills/feishu-doc-collab ~/.kiro/skills/feishu-doc-collab
ln -s $(pwd)/skills/generate-agents-md ~/.kiro/skills/generate-agents-md
ln -s $(pwd)/skills/sync-mr ~/.kiro/skills/sync-mr
ln -s $(pwd)/skills/pptx-gen ~/.kiro/skills/pptx-gen
```

### Cursor

```bash
mkdir -p .cursor/rules
for skill in web-probe generate-agents-md sync-mr feishu-doc-collab pptx-gen; do
  sed '1,/^---$/{ /^---$/!d; }' skills/$skill/SKILL.md | \
    sed '1s/^---$/---\ndescription: "'$skill'"\nglobs:\nalwaysApply: false\n---/' \
    > .cursor/rules/$skill.mdc
done
```

### Windsurf

在 Windsurf 设置 → Rules 中，直接粘贴 SKILL.md 的正文内容（去掉 frontmatter）。

### Aider

```yaml
# .aider.conf.yml
read:
  - /path/to/zenkilan-skills/skills/generate-agents-md/SKILL.md
  - /path/to/zenkilan-skills/skills/sync-mr/SKILL.md
```

### 其他工具

只要 AI 编码工具支持「自定义系统指令」或「读取额外文件作为上下文」，都可以直接使用 SKILL.md 的正文部分。YAML frontmatter 是可选元数据，去掉不影响功能。

## 依赖说明

| Skill | 额外依赖 |
|-------|---------|
| web-probe | Node.js + `npm install`（安装 playwright-core） |
| feishu-doc-collab | 飞书 MCP 端点（[配置方式](./skills/feishu-doc-collab/README.md)） |
| generate-agents-md | 无 |
| sync-mr | `glab` CLI（GitLab MR 操作） |
| pptx-gen | Python 3 + `lxml` + `PyMuPDF`；Keynote（macOS）或 LibreOffice（视觉 QA）；Node.js + PptxGenJS 仅用于用户明确无模板时的可选自由设计回退 |

## 许可

MIT — 随便用，不需要署名。
