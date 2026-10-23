# content.json 结构

一个 MR 对应一个 JSON。渲染器只认这个结构，字段缺失或有占位符会直接失败。

```json
{
  "schema_version": 1,
  "meta": { ... },
  "overview": { ... },
  "features": [ ... ],
  "files": [ ... ],
  "chain": { ... },
  "design": { ... },
  "steps": [ ... ],
  "database": { ... },
  "tests": { ... },
  "verify": { ... },
  "glossary": [ ... ],
  "open_questions": [ ... ]
}
```

`glossary` 与 `open_questions` 可省略；其余必填。所有文本支持两种内联语法：`` `code` `` 与 `**bold**`。

---

## meta

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | MR 标题原文 |
| `subtitle` | string | 一句话副标题（页面暂未展示，留给后续） |
| `project` | string | `group/project`，用于页面标注与 localStorage key |
| `mr_iid` | int | MR/PR 编号（本地模式没有编号就填 0，用 `mr_label` 展示） |
| `mr_url` | string | MR/PR 链接，页面右上角跳转用；为空时按钮隐藏 |
| `platform` | string | 可选，`gitlab` / `github` / `gitee` / `bitbucket` / `generic` / `local`，决定右上角按钮写哪个平台名 |
| `mr_label` | string | 可选，编号的展示形式，如 `#128`、`change 4711`、`main..feature/x`；不填则自动 `!<mr_iid>` |
| `author` | string | `显示名 (@username)` |
| `source_branch` / `target_branch` | string | 源/目标分支 |
| `state` | string | `merged` / `opened` / `closed`，页面会翻译 |
| `created_at` / `merged_at` | string | `YYYY-MM-DD` 即可 |
| `head_sha` | string | 走读所依据的 commit；必须与 `context/` 一致 |
| `generated_at` | string | 生成日期 |
| `stats` | object | `files` / `additions` / `deletions` / `commits`，与 `mr.json` 一致 |
| `tags` | string[] | 2–4 个短标签，显示在标题上方 |

## overview

| 字段 | 说明 |
|---|---|
| `one_liner` | 一句话说清「改了什么、为什么」，不要复述标题 |
| `problem.headline` | 问题的短标题，最好是一个具体现象 |
| `problem.body` | 2–4 句机制解释：什么条件下、哪个环节、发生了什么 |
| `problem.evidence` | 证据列表；每项 `{text, ref}`，`ref` 写来源（如 `MR 描述`、`issue #4711`、`活动 9001`） |
| `solution` | 3–5 条解决动作，按「先…再…」排序 |
| `impact` | 影响面；每项 `{area, detail, level}`，`level` 为 `high/medium/low` |
| `risk.level` | `低/中/高`（自由文本） |
| `risk.items` | 2–4 条真实风险：存量、兼容、变体、回滚 |
| `reading_time` | 预估分钟数，5–15 |

## features

功能视角，不是文件视角。

```json
{"title":"同一用户重复领券被挡住","status":"fixed","detail":"...","files":["..."],"step":"s2"}
```

- `status`：`fixed`（已修复）/ `changed`（行为变了）/ `unchanged`（明确没变）。
- `step` 可选；有则整行可点击跳转。

## files

```json
{"path":"internal/...go","role":"core","change":"modified","additions":11,"deletions":4,"summary":"...","step":"s2"}
```

- `role`：`core` / `test` / `config` / `migration` / `doc` / `generated` / `context`。
- `change`：`added` / `modified` / `deleted` / `renamed` / `context`。
- `context` 表示「没改，但读懂本次变更必须看」，页面会排在改动文件之后，变更列显示 `—`。
- `summary` 写「这个文件为什么在这个 MR 里」，不是内容摘要。

## chain

线性链路，从上到下渲染。至少 4 个节点。

```json
{
  "summary":"一次操作如何从入口走到存储",
  "nodes":[
    {"id":"ui","lane":"前端","label":"编辑器","detail":"...","files":["..."],"step":"s2"}
  ],
  "edges":[{"from":"ui","to":"api","label":"POST /api/x"}]
}
```

- `lane`：`前端` / `网关` / `后端` / `MySQL` / `Redis` / `运行时` / `消息队列` / `外部系统`。
- `files` 写文件名即可（页面用小号等宽字体展示）。
- `edges.to` 必须是已存在的节点 id；页面按 `nodes` 顺序连线，边只用来取标签。

## design

```json
{
  "summary":"这次取舍的主题",
  "decisions":[
    {"question":"为什么…？","choice":"…","why":"…","cost":"…"}
  ]
}
```

`cost` 可选。每个 decision 应该能独立成立：问题、选择、理由、代价。

## steps

```json
{
  "id":"s2",
  "nav":"索引兜底",
  "title":"表结构兜底：给插入加一条唯一索引",
  "kicker":"最小改动",
  "file":"internal/coupon/grant.go",
  "lines":"L42-L67",
  "goal":"这一步解决什么",
  "why_first":"为什么先看这里",
  "snippets":[{"label":"...","lang":"go","code":"...","highlight":[6,9],"note":"..."}],
  "diff":{"label":"...","lang":"go","patch":"..."},
  "explain":["...","..."],
  "takeaway":"带走这一条",
  "next":"下一步去看…"
}
```

- `id`：`^[a-z][a-z0-9-]*$`，全页唯一，用作锚点 `#s2`。
- `nav`：左侧导航用的短标签（≤8 字），不填则用 `title`。
- `file` + `lines`：必须能在 head sha 上核对；`lines` 是给人看的（`L972-L982`），渲染器不解析。
- `snippets[].code`：从 `git show <sha>:<path>` 原样复制，8–40 行为宜；`highlight` 是**片段内**行号（从 1 开始）。
- `snippets[].lang`：`go` / `sql` / `yaml` / `sh` / `js` / `text`。
- `diff` 与 `snippets` 至少有一个。完整 diff 适合「改名/移动」这类需要看上下文的步骤。
- `explain`：3–5 条，每条一个判断，不要复述代码。
- `takeaway`：一句话，读者合上页面能记住的结论。
- `next`：把读者送到下一步的问题，而不是「下一节」。

## database

```json
{
  "has_change": true,
  "headline":"加唯一索引挡并发，同时清理存量重复行",
  "summary":"...",
  "tables":[{"name":"coupon_grant","op":"ALTER","ddl":"...","note":"..."}],
  "steps":["迁移步骤 1","..."],
  "compatibility":"...",
  "rollback":"..."
}
```

- `has_change=false` 时 `tables` 必须为空数组，但 `summary` 仍要写数据面影响（新增行、存量处理、是否需要回填）。
- `has_change=true` 时至少一个 table，`ddl` 原样贴，不要转述。
- `steps` 是执行顺序，不是描述。

## tests

```json
{
  "strategy":"一句话说明测试策略",
  "cases":[{"name":"TestX","type":"unit","file":"...","covers":"...","assert":"..."}],
  "commands":["go test ./..."],
  "gaps":["没有接口级测试覆盖…"]
}
```

- `type`：`unit` / `integration` / `e2e` / `manual`。
- `gaps` 很重要：写清哪些路径没被测到，比堆「已通过」有价值。

## verify

```json
{
  "environment":"测试环境；活动 9001、用户 10086",
  "preconditions":["镜像已部署","账号有编辑权限"],
  "steps":[{"action":"...","expect":"...","observe":"...","fail":"..."}],
  "regression":["其他活动的领券链路不应受影响"]
}
```

- `action` 是一个可执行动作，带具体对象（活动 9001、user_id=10086）。
- `expect` 是用户能看到的结果，不是内部状态。
- `observe` 是去哪看（页面区域、运行记录、日志字段）。
- `fail` 是失败时的第一排查动作。

## glossary / open_questions

```json
"glossary":[{"term":"幂等键","desc":"..."}],
"open_questions":["存量重复数据是否批量清理？"]
```

只收本 MR 里出现、外行会卡住的词；`open_questions` 收真实未决问题，不要凑数。

---

## 校验规则（render.py）

失败：

- 缺必填字段、类型不对、空字符串；
- 文本含 `TODO` / `待填` / `XXX`；
- 步骤 id 重复或不符合命名；
- 步骤既没有 `snippets` 也没有 `diff`；
- `chain.edges` 引用了不存在的节点；
- `database.has_change=true` 但没有 `tables`。

警告（不阻断）：

- 步骤数 < 3；
- 改动文件数多于步骤数；
- `steps[].file` 不在 `files[]` 里；
- 步骤没有 `explain`。
