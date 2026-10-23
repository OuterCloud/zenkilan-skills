---
name: mr-walkthrough
version: 1.0.0
description: "把一个 MR/PR 读透并生成单文件、离线可看的沉浸式 HTML 走读页：功能影响面、文件地图、端到端开发链路、设计取舍、按依赖顺序的代码步骤、数据库改造、测试设计、人工验收步骤。支持 GitLab、GitHub、Gitee、Bitbucket、任意 .diff/.patch 链接和本地分支对比。用户说\"读懂这个 MR\"\"讲解这个 MR\"\"MR 走读\"\"PR 走读\"\"把 MR 做成网页\"\"代码变更走读\"\"MR walkthrough\"时使用。"
metadata:
  requires:
    bins: [python3]
---

# MR Walkthrough

把一条 MR 从「一堆 diff」变成「一条可以按顺序走完的开发故事」。

产出是一个**单文件 HTML**（无 CDN、无外部依赖，双击即开），左侧是章节与进度，右侧一屏一节；支持 `←/→` 或 `j/k` 翻页、`F` 专注模式、验收步骤勾选自动保存。

## 先决条件

1. 目标 MR/PR 的访问凭证：`--token`，或平台环境变量（`GITLAB_TOKEN`、`GITHUB_TOKEN`/`GH_TOKEN`、`GITEE_TOKEN`、`BITBUCKET_TOKEN`），或已登录的 `glab` / `gh`（token 从 CLI 配置读取）。公开仓库、`.diff` 链接、本地模式不需要。
2. 本地有对应仓库（强烈建议）：脚本会用 `git show <head_sha>:<path>` 导出 MR 版本的文件全文，后续分析必须基于这个版本，**不要读工作区当前分支**（可能已经领先或落后于 MR）。
3. 目标 MR/PR 的 URL，或简写 `group/project!123`、`owner/repo#123`、`123 --project ...`。

仓库不在本地也能跑：脚本会退化为只取 API 的 diff，但走读质量会下降（缺少上下文，行号也可能对不上）。这种情况下要在页面里说明。

## 支持的平台

`mr_fetch.py` 把各平台的数据归一化成同一份快照，后续 Phase 完全一致。

| 来源 | 怎么识别 | 认证 |
|---|---|---|
| GitLab（gitlab.com / 自建） | 链接含 `/-/merge_requests/<n>` | `GITLAB_TOKEN`，或 `glab auth login` |
| GitHub（含 Enterprise） | 链接含 `/pull/<n>` | `GITHUB_TOKEN` / `GH_TOKEN`，或 `gh auth login` |
| Gitee | 链接含 `/pulls/<n>` | `GITEE_TOKEN` |
| Bitbucket Cloud | 链接含 `/pull-requests/<n>` | `BITBUCKET_TOKEN`（app password 另给 `BITBUCKET_USERNAME`） |
| 任意平台（Gerrit、Bitbucket Server、自建系统…） | 任何 `.diff` / `.patch` 链接 | 私有链接用 `GENERIC_TOKEN` |
| 本地仓库 | `--local --base-ref <a> --head-ref <b>` | 不需要 |

后两种是降级模式，只有 diff（通用模式能解析 `.patch` 里的 commit），没有评论、CI 状态和标题描述。走读里要写明「上下文未与平台交叉核对」，并把推断放进 `open_questions`。

链接形态有歧义（自建实例、非标准路径）时用 `--platform gitlab|github|gitee|bitbucket|generic` 强制指定。

## 工作流

### Phase 1 取数

```bash
# 本 skill 所在目录；Claude Code 一般是 ~/.claude/skills/mr-walkthrough
SKILL="$HOME/.kiro/skills/mr-walkthrough"
WORK=.mr-walkthrough/acme-order-service-128   # 不传 --out 时脚本自己写到 .mr-walkthrough/<project>-<number>

# GitLab / GitHub / Gitee / Bitbucket：直接给链接
python3 "$SKILL/scripts/mr_fetch.py" "https://gitlab.example.com/acme/order-service/-/merge_requests/128" \
  --repo /path/to/repo --out "$WORK"
python3 "$SKILL/scripts/mr_fetch.py" https://github.com/acme/order-service/pull/128 \
  --repo /path/to/repo --out "$WORK"

# 简写：域名从本地 origin 推断，推断不出来时 --host
python3 "$SKILL/scripts/mr_fetch.py" acme/order-service!128 --host gitlab.example.com --repo /path/to/repo
python3 "$SKILL/scripts/mr_fetch.py" acme/order-service#128 --host github.com --repo /path/to/repo

# 没有 API 的平台：给 diff/patch 链接
python3 "$SKILL/scripts/mr_fetch.py" https://review.example.com/changes/4711.diff --out "$WORK"

# 连 diff 都拿不到：本地两个 ref 对比（只比较已提交内容）
python3 "$SKILL/scripts/mr_fetch.py" --local --base-ref origin/main --head-ref feature/x \
  --repo /path/to/repo --out "$WORK"
```

产出：

| 文件 | 用途 |
|---|---|
| `mr.json` | 平台（`platform`）、标题、描述、作者、分支、head/base sha、文件/行数/commit 统计 |
| `changes.json` | 每个文件的 unified diff（含新增/删除行数） |
| `commits.json` | commit 列表 |
| `discussions.json` | 人工 review 评论（system note 已剔除；通用/本地模式为空） |
| `context/<path>` | MR head sha 下的文件全文 |
| `history.json` | 每个改动文件最近 3 条提交，用来回答「为什么之前是这样」 |

先读 `mr.json` 的 `description`：作者的背景、改动意图、验证方式通常都在里面，是走读叙事的骨架。描述为空时，用 commits + discussion + 代码补，并把推断写进 `open_questions`，不要伪装成事实。

### Phase 2 读透（决定成品质量的一步）

按这个顺序读，边读边记「因果表」：

1. **症状**：MR 描述、评论、commit message 里提到的现象、报错、工单号。
2. **每个 hunk**：逐个读，不要只读 `+` 行；`-` 行和上下文同样说明约束。
3. **上下游**：对每个改动的函数/类型，用 `grep` 找调用方与被调用方；至少追到「谁触发它」和「它影响谁」。
4. **数据面**：是否新增/修改参数、字段、表、缓存 key、配置项？存量数据怎么办？
5. **测试**：新增用例在锁什么行为？哪些路径没被测到？

硬规则：

- 代码片段必须从 `git show <head_sha>:<path>` 里取，**不要凭记忆重写**，行号以该版本为准。
- 只写代码能证明的事。注释、命名、MR 描述可以作为「意图」引用，但要标明来源。
- 读到与 MR 描述矛盾的地方，停下来核对代码，以代码为准，并在 `open_questions` 里标出。

### Phase 3 写内容 JSON

按 [references/content-schema.md](references/content-schema.md) 写 `<WORK>/content.json`。

最快的起步方式：复制 [examples/mr-128.json](examples/mr-128.json) 改字段。它是完整样例（7 步、9 节点链路、含一次带 DDL 的数据库改造，验收清单齐全）。

写作要求见 [references/writing-guide.md](references/writing-guide.md)，核心只有三条：

- **每一步回答一个问题**：为什么需要它、改在哪、它把读者送到哪。
- **顺序按依赖，不按提交**：先契约/入口，再核心机制，再下游影响，最后数据与验收。
- **具体到可核对**：文件、行号、函数名、参数名、表名，而不是「优化了逻辑」。

### Phase 4 渲染

```bash
python3 "$SKILL/scripts/render.py" "$WORK/content.json" --out docs/mr-walkthrough/mr-<iid>.html --open
```

`render.py` 会先校验结构，缺字段/占位符未填/链路边引用不存在的节点都会直接失败，不会产出半成品。

### Phase 5 自检

- [ ] `meta.stats` 与 `mr.json` 一致（文件数、增删行、commit 数）。
- [ ] 每个改动文件都出现在 `files[]`；除纯格式化/生成文件外，每个产线改动至少对应一步。
- [ ] 每一步都有 `file` + `lines`，且 `snippets` 与 `context/` 中的内容逐字一致。
- [ ] `chain` 至少 4 个节点，覆盖「入口 → 处理 → 存储/运行时」，关键节点挂 `step`。
- [ ] `database` 即使没有 DDL，也写清数据面影响与存量处理。
- [ ] `verify` 的每一步都有「操作 / 预期 / 观察点 / 不通时怎么办」。
- [ ] 全文没有 TODO、待补、占位符；不确定的写进 `open_questions`。
- [ ] 用浏览器实际打开，键盘翻页、代码高亮、勾选保存都正常。

## 章节该写什么

| 章节 | 必须回答 | 常见错误 |
|---|---|---|
| 概览 | 一句话结论、问题是什么、怎么解、影响谁、风险多大 | 复述 MR 标题；没有问题机制 |
| 功能影响面 | 哪些用户可见行为/内部契约变了，哪些没变 | 把文件列表当功能列表 |
| 文件地图 | 每个文件为什么在这个 MR 里；区分改动与只读上下文 | 只列路径不解释 |
| 开发链路 | 一次操作从入口到存储/运行时的完整一跳一跳 | 只画分层框图，不挂代码 |
| 设计取舍 | 为什么选 A 不选 B，代价是什么 | 把 MR 描述抄一遍 |
| 逐步走读 | 先看哪、改了什么、为什么、下一步 | 按 diff 顺序平铺；没有因果 |
| 数据库改造 | 表/字段/索引/迁移/兼容/回滚 | 没 DDL 就留空 |
| 测试设计 | 单测锁什么、缺什么、怎么跑 | 只写「已通过」 |
| 人工验收 | 前置条件、操作、预期、观察点、失败排查 | 写成「验证功能正常」 |

## 步骤怎么排

对多数 MR，5–9 步最舒服。推荐叙事：

1. **契约/入口**：测试、接口定义、调用方，先让读者知道「什么叫改对了」。
2. **核心机制**：真正改变行为的那个函数/分支，通常 1–2 步。
3. **为什么必须这样做**：约束来自哪里（类型系统、隐藏字段、历史迁移、门禁）。
4. **设计取舍**：复用还是复制、加字段还是加表、在哪里兜底。
5. **下游影响**：谁开始认这个改动，谁仍然不认。
6. **数据与验收**：存量怎么办、人怎么点一遍。

只有 1–2 个文件的小 MR 也可以有 5 步——步骤是按「理解单元」切的，不是按文件切的。

## 输出位置

默认写到目标仓库的 `docs/mr-walkthrough/mr-<iid>.html`；仓库没有 `docs/` 时写到 MR 工作目录。文件名带 MR 号即可，页面内已经包含标题与时间。

## 失败与边界

- **token 缺失 / 401 / 403**：按平台提示（GitLab `glab auth login --hostname <host>` 或 `export GITLAB_TOKEN=...`；GitHub `gh auth login` 或 `export GITHUB_TOKEN=...`；Gitee `GITEE_TOKEN`；Bitbucket `BITBUCKET_TOKEN`）。不要尝试匿名访问私有仓库。
- **平台不支持 / 路径不标准**：先用 `--platform` 指定；仍不行就给该平台的 `.diff` / `.patch` 链接走通用模式，或用 `--local` 比两个 ref。
- **本地仓库与目标项目不一致**：脚本会跳过 context 导出。改用 `--repo` 指向正确仓库，或在另一个目录 clone 后重跑。
- **diff 被折叠（>200 文件 / >20k 行）**：`changes.json` 里会有 `too_large` 标记。按模块分组，选核心链路做走读，并在概览里说明「本页覆盖核心路径，其余文件见 MR」。
- **生成文件 / lock 文件 / 纯格式化**：列进 `files[]` 标 `generated`，不单独开步骤。
- **MR 已合并 / 已关闭 / DECLINED**：照常生成，`meta.state` 如实填写（统一成 `merged` / `opened` / `closed`）。
- **没有本地仓库**：可以只基于 diff 生成，但要在概览的风险里注明「行号与上下文未与本地代码交叉验证」。
- **通用 diff / 本地模式**：没有评论与 CI 状态，`discussions.json` 为空。走读里要说明这是降级来源，不要编造 review 意见。

## 参考

- [references/content-schema.md](references/content-schema.md)：字段定义与约束。
- [references/writing-guide.md](references/writing-guide.md)：每章写作范式与反例。
- [examples/mr-128.json](examples/mr-128.json)：完整样例（虚构 MR，可直接改字段复用）；`examples/mr-128.html` 是它的渲染效果。
- [tests/test_providers.py](tests/test_providers.py)：平台适配层的 fixture 测试，改 `platforms/` 后跑 `python3 -m unittest discover -s tests -v`（不联网）。
