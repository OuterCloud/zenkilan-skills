---
name: generate-agents-md
version: 3.7.0
description: "为 git 项目生成或更新 AGENTS.md（面向 AI 编码 agent 的项目说明，agents.md 开放标准）。当用户说'生成 AGENTS.md'、'加 agent 指令文件'、'让 AI 看懂这个项目'、'补一下 agent 配置'时触发。也用于 monorepo 子包的嵌套 AGENTS.md。"
---

# Generate AGENTS.md

生成符合 [agents.md 开放标准](https://agents.md) 的项目说明文件。

## 先分清是哪个东西

三者常被混淆，规范完全不同：

| 文件 | 规范 | 格式 | 用途 |
|------|------|------|------|
| **`AGENTS.md`**（本 skill 的目标） | agents.md 开放标准（Agentic AI Foundation / Linux Foundation 旗下） | 标准 Markdown，**无必填字段**；frontmatter 在此格式中无语义 | 项目的构建/测试/约定，所有 agent 通读 |
| `.github/agents/*.md` | GitHub Copilot custom agents | **依赖 frontmatter**（name/description） | 定义 agent 人格（@docs-agent 等） |
| `CLAUDE.md` / `.cursorrules` / `.kiro/steering/` | 各家私有 | 各异 | 单一工具的指令 |

若用户要的是 Copilot 的 agent 人格，不是本 skill —— 那需要 frontmatter 和 persona 定义。

Codex、Cursor、Jules、Aider、goose、Zed、Warp、Devin、Junie、Gemini CLI、Copilot coding agent 等均支持，写一份通吃。

## 核心约束：context 预算

**AGENTS.md 会被载入 agent 的每一轮上下文。每一行都在为每一次请求付费。**

- 官方参考示例约 **20 行**
- 目标：根文件 **30-80 行**；>120 行必须处理
- 逐行判据：**这一行会改变 agent 的行为吗？** 不会就删

内容确实很多时，有三条出路，按优先级：

1. **外链**（首选）：`E2E 环境搭建见 docs/testing-e2e.md` —— agent 需要时自己读，不需要时不付费
2. **拆嵌套**：monorepo 各子包放自己的 AGENTS.md
3. **删**：能从代码/配置直接看出来的，不写

## 规范硬事实（官方 FAQ）

1. **没有必填字段** —— 标准 Markdown，标题随意
2. **就近生效**：离被编辑文件最近的 AGENTS.md 胜出；用户对话中的指令覆盖一切
3. **⚠️ 列出的检查命令 agent 会自动执行** —— 它会尝试跑你写的测试/lint 并修复失败。**因此破坏性命令不能作为常规检查列出**（`db:reset`、`deploy`、`migrate:down`、`push --force`）。要么不写，要么显式标注「需用户确认」
4. **是活文档** —— 见文末维护循环
5. **迁移**：`mv AGENT.md AGENTS.md && ln -s AGENTS.md AGENT.md`（官方 FAQ 给的写法）。
   注意这个 symlink 同样有写入穿透风险 —— 只是 `AGENT.md`（单数）是历史遗留名，
   主流工具不会主动写它，风险远低于 `CLAUDE.md`。若你的环境有工具会写 `AGENT.md`，
   改用一行 `@AGENTS.md` 指针文件（见 Step 5）。

---

## 执行流程

### Step 0：幂等检查（先做，别覆盖）

```bash
ls AGENTS.md AGENT.md CLAUDE.md .cursorrules .github/copilot-instructions.md 2>/dev/null
```

| 发现 | 动作 |
|------|------|
| 已有 `AGENTS.md` | **读完再改**：补缺失、修过期，保留人工维护的规则。结束时要能列出改了哪几条 |
| 有 `CLAUDE.md` / `.cursorrules` 等私有文件 | 内容多半可复用 → 迁移进 AGENTS.md，原文件改 symlink 保兼容 |
| 有 `AGENT.md`（单数） | 按硬事实 #5 重命名 + symlink |
| 都没有 | 全新生成 |

### Step 1：从权威来源探测

**CI 配置最权威 —— 它是实际会跑的东西。**冲突时：CI > 清单 scripts > README（README 常年久失修）。

```bash
# 1) CI：真正被执行的命令
cat .github/workflows/*.y*ml .gitlab-ci.yml Jenkinsfile .circleci/config.yml 2>/dev/null

# 2) 人写的约定（常含隐性规则，且是唯一能看出"为什么"的地方）
cat CONTRIBUTING.md 2>/dev/null
git log --oneline -20      # Conventional Commits？
git branch -r | head       # 分支命名习惯

# 3) 结构：列真实目录（限深 2 层）
#    注意：不要用 `awk -F/ 'NF>1{print $1"/"$2}'` —— 它会把深度 2 的文件当成目录，
#    且 git ls-files 会给非 ASCII 路径加引号，污染输出。
git -c core.quotepath=false ls-files -z \
  | xargs -0 -n1 dirname | cut -d/ -f1-2 | sort -u | grep -v '^\.$' | head -40

# 4) monorepo 检测：按【内容】判定，不能只看文件是否存在
#    （反例：仓库有 pnpm-workspace.yaml 但里面只写了 allowBuilds，并非 monorepo）
grep -qE '^[[:space:]]*packages:' pnpm-workspace.yaml 2>/dev/null && echo "pnpm workspace"
grep -q '"workspaces"' package.json 2>/dev/null            && echo "npm/yarn workspaces"
grep -q '^\[workspace\]' Cargo.toml 2>/dev/null             && echo "cargo workspace"
ls go.work lerna.json 2>/dev/null                            # 存在即是
```

各生态提取什么：

| 生态 | 命令来源 | 版本/依赖 | linter 配置 |
|------|---------|-----------|-------------|
| Node | `package.json` scripts、`packageManager` 字段 | dependencies | `.eslintrc.*` / `eslint.config.*` / `biome.json` / `.prettierrc.*` |
| Go | `Makefile` / `justfile`；`go test ./...` | `go.mod`（go 指令即版本） | `.golangci.yml` 或 `.golangci.yaml` |
| Python | `pyproject.toml [tool.*]`、`tox.ini`、`Makefile` | `pyproject.toml`、`.python-version` | `ruff.toml` `setup.cfg` |
| Rust | `cargo test/build`、`Makefile.toml` | `Cargo.toml` edition + deps | `rustfmt.toml` `clippy.toml` |
| Java/Kotlin | `pom.xml` / `build.gradle` tasks | 同左 | checkstyle / spotless 配置 |

另查 `.editorconfig`；TS 项目查 `tsconfig.json` 的 `strict` 与 `paths` 别名。

### Step 2：实跑验证（不是 `which`）

写进去的命令必须真能跑。**按此顺序 —— install 必须先行，快的先跑好早失败：**

```
install → lint → build → test
```

- 报错/不存在 → 修正后再写，或补前置条件（如「需先 `docker compose up -d`」）
- **单条超过约 2 分钟就别跑全量**，跑最小子集确认命令形态正确即可（如只跑单个测试文件）
- 环境不具备（缺凭证、需外部服务）→ 照写，但注明依赖前提
- **绝不为"验证"而执行破坏性命令**（硬事实 #3）
- ⚠️ **命令本身失败 ≠ 检查通过**。看到「无输出」先确认是「跑了没发现问题」还是「命令根本没跑起来」。典型坑：macOS 无 `timeout` 命令，`timeout 60 go test ...` 直接 command not found、零输出，会被误读成测试挂起或全过。用工具自带的超时（`go test -timeout 60s`），并检查退出码。

### Step 2.1：写入命令前的三问

凡是要写进 AGENTS.md（或本 skill）的 shell 命令，先过这三问。三类缺陷都只在特定条件下暴露，单次顺利执行证明不了什么：

| 三问 | 对应缺陷 | 真实踩过的坑 |
|------|---------|-------------|
| **换个环境还成立吗？** | 可移植性 | `\b` 是 GNU 扩展、非 POSIX ERE，不保证跨 grep 实现；`xargs` 对空输入的处理 BSD 与 GNU 不一致；macOS 没有 `timeout` |
| **跑第二遍会怎样？** | 幂等性 | `echo ... >> .aider.conf.yml` 重复追加出多条；`ln -s` 目标已存在时报 `File exists` |
| **输入为空会怎样？** | 边界输入 | `find` 无命中时管道给 `dirname` 的参数为空，可能把路径解析成项目根目录 |

答不上来就就地验证：**在临时目录跑一遍、连跑两遍、喂空输入再跑一遍**。三次都符合预期才写进去。

### Step 3：写文件

覆盖六个高价值维度（2500+ 仓库分析结论）：**命令、测试、结构、代码风格、Git 流程、边界**。
命令放最前 —— agent 引用最频繁。每个维度只写「agent 不看就会做错」的部分。

### Step 4：monorepo 拆嵌套

根文件放通用规则，子包放自己的。就近生效，子包不必重复根规则。

```
AGENTS.md                  # 通用：workspace 命令、提交规范
packages/api/AGENTS.md     # 专属：DB 迁移、路由约定
packages/web/AGENTS.md     # 专属：组件结构、状态管理
```

判据 —— **看差异的性质，不看数量**。命中任一条就值得独立文件：

- 子包有**自己的构建/测试命令**，而非根命令加 filter（`pnpm --filter x test` 不算）
- 子包有**自己的 linter / tsconfig / 编译配置**
- 子包有**独立的部署目标或运行时**（不同镜像、不同集群、不同发布节奏）
- 子包的**技术栈与根不同**（根是 TS，某包是 Go）

只是目录职责不同 → **不拆**，写进根文件的 Structure 一行即可。

不要用「差异超过 N 条」这类阈值：两条结构性差异（独立产物 + 独立 lint 配置）就该拆，四条无关紧要的职责描述差异不该拆。

### Step 5：兼容性收尾（按需）

这一步也要幂等 —— 重复执行不得产生重复条目或覆盖已有内容：

```bash
# 让私有格式指向同一份内容。
# ⚠️ 不要用 symlink：写入会穿透符号链接。Cursor / Claude Code 等工具会主动往
#    CLAUDE.md 追加内容（memory、/init 等），若它是指向 AGENTS.md 的 symlink，
#    这些写入会静默污染 AGENTS.md，冲掉人工维护的规则。已实测复现。
# ✅ 用一行指针文件：工具照样能追加，但脏内容留在 CLAUDE.md，AGENTS.md 不受影响。
#    （cnp/wutong 就是这么做的）
[ -e CLAUDE.md ] || [ -L CLAUDE.md ] || echo '@AGENTS.md' > CLAUDE.md

# Aider：先查再写，避免重复追加
grep -qs 'AGENTS.md' .aider.conf.yml || echo "read: AGENTS.md" >> .aider.conf.yml
```

**Gemini CLI 的 `.gemini/settings.json` 是 JSON，必须读出→合并→写回。**
绝不能 `echo >> settings.json` —— 那会产出非法 JSON 且工具静默忽略配置。
不依赖 `jq`（CI 镜像常没有），用 python3。四种场景均已实测：文件不存在 / 已有其他配置
不丢失 / 连跑三次幂等 / 遇非法 JSON 报错且不覆盖原文件。

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('.gemini/settings.json')
p.parent.mkdir(parents=True, exist_ok=True)
cfg = {}
if p.exists() and p.stat().st_size:
    try:
        cfg = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise SystemExit(f'.gemini/settings.json 不是合法 JSON，请先人工修复：{e}')
cfg.setdefault('context', {})['fileName'] = 'AGENTS.md'
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('已写入 .gemini/settings.json')
PY
```

若仓库已存在 symlink 形式的 `CLAUDE.md`，建议换成指针文件 —— 但那是既有文件，
按 Step 0 幂等原则先问用户，不要擅自替换。

---

## 内容规则

### 1. 命令：完整可粘贴，含 flag、用途、前置条件

违反后果：agent 照着跑失败，或自己猜 flag。

```
❌ - Test: run tests
❌ - Test: `npm test`
✅ - Test: `pnpm test` — Vitest，覆盖率门槛 80%，提交前须全绿
✅ - Test 单用例: `pnpm vitest run -t "<name>"`
```

### 2. 结构：写职责与禁区，不写目录名

agent 会自己 `ls`。它不知道的是「这目录该放什么、不该放什么」。

违反后果：文件被放错位置。

```
❌ - `src/` — 源码
✅ - `src/lib/` — 纯逻辑，不得 import React（Node 侧脚本复用）
✅ - `src/components/` — 一组件一目录：index.tsx + styles.css + __tests__/
✅ - `db/migrations/` — 只增不改，动了已合并的迁移会炸线上
```

### 3. 代码风格：只写 linter 管不到的，示例取自本项目

缩进/引号/分号交给 lint —— 写进来是纯浪费，agent 跑一次 lint 就知道了。要写的是**架构级约定**：错误处理模式、分层依赖方向、状态管理选型。

违反后果：token 浪费；用 hello-world 当示例还会让 agent 学到不属于本项目的风格。

示例必须能指出来源文件（"摘自 `src/lib/api.ts`"）。

### 4. 边界：三档，具体到文件与操作

违反后果：凭空想象的禁令变成噪音，把真正危险的那条淹没。

```
❌ 🚫 Never: 做坏事
✅ - ✅ Always: 改完 prisma/schema.prisma 必须跑 `pnpm prisma generate`
✅ - ⚠️ Ask first: 加依赖；改 tsconfig paths；改 CI 配置
✅ - 🚫 Never: 绕过 Prisma 写裸 SQL
✅ - 🚫 Never: 改 db/migrations/ 下已合并的文件
✅ - 🚫 Never: 自动跑 `pnpm db:reset`（清库，需用户确认）
```

判据：**这条对应过一次真实踩坑吗？** 不能说出来源就删。

关于「Never commit secrets」：2500 仓库分析显示这是最常见的**有效**约束，但前提是本仓库真有该风险面 —— 存在 `.env.example`、凭证配置、或历史上泄漏过。纯模板式照抄就是噪音。

### 5. 结构性断言必须逐仓库 grep 验证，不得跨仓库套用

「A 不得 import B」「domain 只依赖标准库」「pkg/ 可对外复用」这类**分层/依赖断言最容易出错**，因为它们形式上像通用最佳实践，套用时毫无阻力 —— 但每个仓库的现实完全不同。

违反后果：agent 以为存在一条约束，可能为「遵守」它扭曲新代码，或去「修复」根本不存在的违规，造成无意义 churn。

**每条结构性断言都要配一条能跑出 0 结果的 grep，并在验证时实跑：**

```bash
# 断言「pkg/ 不得 import internal/」的验证
grep -rn "<module-path>/internal" pkg --include='*.go' | wc -l   # 必须为 0

# 断言「domain 只依赖 encoding/json 与 time」的验证
grep -rhE '^\s+"' internal/domain --include='*.go' | tr -d ' "' | sort -u
```

跑不出 0 就改成描述现状，而不是删掉 —— 「这里的 `pkg/` **不是**对外可复用层，两个包都 import `internal/`，别假设能独立抽取」同样有价值，甚至更有价值（Go 惯例会让人默认 `pkg/` 是公共库）。

**批量为多个仓库生成时风险最高** —— 在 A 仓库核实为真的断言，到 B 仓库很可能是假的。同一批次里出现过三个仓库三种现实：一个 `pkg/` 确实干净、一个生产代码就在跨层引用、一个有严格单向依赖。逐个验，不要复用结论。

### 6. 深内容外链，不内联

`E2E 环境搭建见 docs/testing-e2e.md`。罕用细节内联 = 每一轮都为它付费。

### 7. 不重复 README，不写零信息量句子

「本项目是一个现代化 Web 应用」删掉。README 有的、代码里明摆着的，都不写。

---

## 完整示例（这个长度就够）

> **[MUST] 生成时必读 —— 示例里的版本号只是示意。** 实际生成时必须从 `package.json` /
> `go.mod` / `Cargo.toml` 读取，不得手写、猜测或沿用本示例 —— 版本写错比不写更糟，
> agent 会据此选 API 和语法。
>
> （用 `>` 引用块而非 `<!-- -->`：HTML 注释在部分 Markdown 渲染器不可见；放在示例块外，
> 避免被照抄进真实文件。`[MUST]` 前缀便于程序化提取本 skill 的强制项。）

````markdown
# AGENTS.md

## Commands
- Install: `pnpm install`
- Dev: `pnpm dev` — Vite :5173，需先 `docker compose up -d` 起 Postgres
- Build: `pnpm build` — tsc + vite build → dist/
- Test: `pnpm test` — Vitest，覆盖率门槛 80%
- Test 单用例: `pnpm vitest run -t "<name>"`
- Lint: `pnpm lint --fix` — Biome，提交前必跑

## Stack
TypeScript 5.4 strict · React 18 · Vite 5 · Prisma 5 + Postgres 16 · pnpm 9

## Structure
- `src/routes/` — TanStack Router 文件式路由，文件名即 URL
- `src/lib/` — 纯逻辑，不得 import React（Node 脚本复用）
- `prisma/` — schema 改动后必须 `pnpm prisma generate`
- `db/migrations/` — 只增不改，动了已合并的会炸线上

## Conventions
错误处理统一返回 Result 不 throw（linter 管不到，容易写错）。摘自 `src/lib/api.ts`：

```ts
async function fetchUser(id: string): Promise<Result<User>> {
  const res = await api.get(`/users/${id}`)
  return res.ok ? ok(res.data) : err(res.error)
}
```

E2E 环境搭建见 `docs/testing-e2e.md`。

## Git
- 分支：`feat/<desc>` `fix/<desc>`，从 main 切
- 提交：Conventional Commits（CI 校验）
- PR 标题：`[<package>] <title>`

## Boundaries
- ✅ Always: 改 schema 后跑 `pnpm prisma generate`
- ⚠️ Ask first: 加依赖、改 tsconfig paths、改 CI
- 🚫 Never: 绕过 Prisma 写裸 SQL
- 🚫 Never: 改 db/migrations/ 下已合并文件
- 🚫 Never: 自动跑 `pnpm db:reset`（清库，需用户确认）
````

---

## 验收门（机械可核验）

```bash
wc -l AGENTS.md                # ≤120，理想 30-80
head -1 AGENTS.md              # 应是 "# ..."，不是 "---"

# 破坏性命令筛查。词边界用 POSIX ERE 的 (^|[^[:alnum:]]) … ([^[:alnum:]]|$) 表达，
# 不用 \b —— 后者是 GNU 扩展、非 POSIX，换 grep 实现可能静默失效。

# 自检必须 fail-closed：不通过就中断，不要带着不可信的 grep 继续筛查。
# 6 用例覆盖 4 负 2 正 —— 不应命中 dropdown/deployment.md/predeploy/undeployed，
# 应命中 deploy/./deploy.sh。
exp=2
got=$(printf 'dropdown\ndeployment.md\npredeploy\nundeployed\ndeploy\n./deploy.sh\n' \
      | grep -cE '(^|[^[:alnum:]])deploy([^[:alnum:]]|$)')
if [ "$got" != "$exp" ]; then
  echo "词边界自检失败（期望 $exp 得 $got）：本机 grep 方言不可信，改用下面的 python3 版" >&2
  exit 1
fi

grep -nE 'db:reset|migrate:down|--force|drop[[:space:]]+(table|database)|(^|[^[:alnum:]])deploy([^[:alnum:]]|$)|rm[[:space:]]+-rf' AGENTS.md
```

**方言无关的替代（推荐在 Alpine / BusyBox 等 CI 镜像里用）。** BusyBox grep 对
`(^|[^[:alnum:]])` 的处理未必与 GNU 一致，而本环境无 Docker 无法实测验证 —— 与其赌，
不如用零宽断言，行为跨平台一致（已验证与 grep 版命中结果逐行相同）：

```bash
python3 - AGENTS.md <<'PY'
import re, sys
PATTERNS = [r'db:reset', r'migrate:down', r'--force', r'drop\s+(table|database)',
            r'(?<![0-9A-Za-z])deploy(?![0-9A-Za-z])', r'rm\s+-rf']
rx = re.compile('|'.join(PATTERNS))
# 内建自检：4 负 2 正
wb = re.compile(r'(?<![0-9A-Za-z])deploy(?![0-9A-Za-z])')
fixture = ['dropdown','deployment.md','predeploy','undeployed','deploy','./deploy.sh']
n = sum(1 for s in fixture if wb.search(s))
assert n == 2, f'词边界自检失败：期望 2 得 {n}'
for i, l in enumerate(open(sys.argv[1], encoding='utf-8'), 1):
    if rx.search(l): print(f'{i}: {l.rstrip()}')
PY
```

命中项不等于错误 —— 但每一条都必须带「需用户确认」标注，否则 agent 可能自动执行。

逐项确认，任一不过就回改：

- [ ] 行数 ≤120
- [ ] 首行非 `---`（无 frontmatter）
- [ ] Commands 每条已在 Step 2 实跑通过，或标注了不可验证原因
- [ ] 破坏性命令未作为常规检查列出（上面 grep 的命中项都有确认标注）
- [ ] 每个代码示例能指出来源文件路径
- [ ] 每条 Never 能说出对应的真实踩坑
- [ ] **每条结构性断言（分层/依赖/禁止 import）都已在本仓库实跑 grep 验证，并能给出那条命令与结果**
- [ ] **写入的命令已过 Step 2.1 三问**：换环境是否成立、跑第二遍是否安全、空输入是否退化正确
- [ ] **Stack 节的版本号逐个来自清单文件**（`package.json` / `go.mod` / `Cargo.toml`），无手写或沿用示例。核验方式：对每个版本号能指出它出自哪个文件的哪一行
- [ ] 无 linter 已强制的风格规则
- [ ] 若原文件存在，能列出本次改动的具体条目

---

## 维护循环

AGENTS.md 靠迭代长好，不靠一次写全。触发补充的信号只有一个：

**agent 犯了错 → 补上「本来能预防这个错」的那一条 → 别的都不加。**

这样每条规则都自带来源，天然满足「边界要有真实踩坑」的判据，也不会膨胀。
反过来，规则长期没被触发过、或对应的代码已重构掉 —— 删。

**让循环真的发生**：靠个人记性维护不住。把这一条写进 `CONTRIBUTING.md` 或 MR/PR 模板的勾选项：

```markdown
- [ ] 若本次改动源于 agent 犯错，已在 AGENTS.md 补上能预防它的规则
```

配套的判断标准：**同一个错误被 agent 犯第二次，就是 AGENTS.md 缺规则的信号**，不是 agent 不行。

除「agent 犯错」外，还有一个必须触发更新的信号：

- **依赖升了 major 版本 → 同步 Commands / Stack 节**。版本漂移后 agent 会照旧版本选 API 和语法，
  而这类错误不会报错、只会写出过时代码。升级 MR 里就该带上 AGENTS.md 的改动。

### 本 skill 自身的迭代记录

见 `references/iteration-log.md` —— 追加式日志，**每次修改 SKILL.md 必须在其中新增一行，
禁止修改或删除已有行**。加不出「来源事件」说明这次改动没有真实触发因素，应重新审视是否必要。

（外链而非内联：该日志随每轮迭代无界增长，而执行本 skill 并不需要读它。
执行必需的内容 —— 流程、内容规则、验收门 —— 一律保留在正文。）


