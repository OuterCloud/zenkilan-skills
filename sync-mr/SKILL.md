---
name: sync-mr
version: 1.3.0
description: "代码变更后的标准MR同步流程：更新测试文档、amend commit + force push、更新MR描述。当用户说'sync-mr'、'同步MR'、'跑一下sync流程'、或代码改完需要提交时触发。"
metadata:
  inclusion: manual
---

# Sync MR

代码变更完成后的标准三步同步流程：

1. **更新测试文档** — 为本次变更补充测试用例
2. **Amend + Force Push** — 合入当前 commit 并推送
3. **更新 MR 描述** — 重新提炼 Summary（不是追加）

---

## 前置检查

⚠️ **变量不跨 shell 调用存活。** agent 通常每一步开一个新 shell，前置检查里设的
`$IID` 到步骤二就没了。空变量的后果很严重：`git add ""` 报错还算好，
`glab mr update "" --description ...` 可能打到错误目标。

因此有两种正确用法，二选一：

- **A（推荐）**：把前置检查 + 某个步骤放在**同一个 shell 调用**里连续执行
- **B**：每步开头重新派生一次。派生是幂等的纯读操作，重复跑无副作用

派生片段（A 和 B 都用这段）：

```bash
set -euo pipefail

# 1. 保护分支不得执行
BRANCH=$(git branch --show-current)
if [[ "$BRANCH" =~ ^(main|master|develop)$ ]]; then
  echo "错误：当前在保护分支 $BRANCH" >&2; exit 1
fi

# 2. 必须有变更
if [ -z "$(git status --porcelain)" ]; then
  echo "无变更，无需同步"; exit 0
fi

# 3. 必须有 opened MR，取出 iid
command -v glab >/dev/null || { echo "缺少 glab：brew install glab" >&2; exit 1; }
IID=$(glab mr list --source-branch="$BRANCH" --state=opened --output json \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["iid"] if d else "")')
if [ -z "$IID" ]; then
  echo "当前分支无 opened MR，请先 glab mr create" >&2; exit 1
fi

# 4. 用前必校验非空 —— 变量丢失时立刻停，不要带着空值往下跑
: "${IID:?IID 为空，重新执行派生}"
echo "分支 $BRANCH → MR !$IID"
```

用户在指令中显式指定了 MR 编号时，优先用用户给的值覆盖 `$IID`。

> `set -euo pipefail` 下 `if` 判断不会误触发退出；但不要改回 `cond && cmd` 链式写法，
> 那种写法在 `set -e` 下的行为容易读错。
>
> 若 agent 不便维持同一 shell，**退而求其次：把派生出的真实值直接写进命令字面量**
> （如 `git add "docs/test_plan_docs/test-plan-mr-42.md"`），而不是留一个可能为空的变量。

---

## 步骤一：更新测试文档

### 路径发现策略

Skill 不写死路径，按以下优先级**自动发现**当前项目的测试文档位置：

1. 检查项目 steering 中是否声明了测试文档路径（如 `.kiro/steering/` 下的配置）
2. 检查是否已存在 `test-plan-mr-*.md` 文件，取其所在目录
3. 回退默认：`docs/test_plan_docs/`

```bash
# 不用 xargs：BSD/GNU 对空输入的处理不同，且 dirname 拿不到参数时行为不一致。
# 多个匹配时按路径排序取第一个，保证同一仓库每次结果一致（-print -quit 的顺序不确定）。
FOUND=$(find . -name 'test-plan-mr-*.md' -not -path './.git/*' | sort | head -1)
if [ -n "$FOUND" ]; then
  TEST_DOC_DIR=$(dirname "$FOUND")
else
  TEST_DOC_DIR="docs/test_plan_docs"
fi
mkdir -p "$TEST_DOC_DIR"
DOC="$TEST_DOC_DIR/test-plan-mr-$IID.md"
echo "测试文档: $DOC"
```

若 `find` 命中多个目录下的文件（历史遗留分散存放），以排序后第一个为准并在回复里
说明选了哪个，让用户有机会纠正 —— 不要静默挑一个。

### 文档命名

命名规则 `test-plan-mr-<iid>.md`（如 `test-plan-mr-42.md`）。
**在命令里一律用 `$DOC` 或 `"$TEST_DOC_DIR/test-plan-mr-$IID.md"`，不要出现字面 `<iid>`。**

### 写入逻辑

| 情况 | 动作 |
|------|------|
| 文件不存在 | 创建，写入标题 + 第一个章节 |
| 文件存在 | 找到最后一个 `## <N>.` 章节，新增 `## <N+1>.` |
| 本次变更已有对应章节且准确 | 跳过 |

编号必须**取现有最大值 +1**，不能用章节计数（编号可能不连续）。已验证的片段：

```bash
# 四种情形均已实测：正常递增 / 文件不存在 / 无编号章节 / 编号非连续(1,3,7→8)
NEXT=$(grep -oE '^## [0-9]+\.' "$DOC" 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -1)
NEXT=$(( ${NEXT:-0} + 1 ))
echo "下一章节号: $NEXT"
```

`sort -n | tail -1` 取最大值；`${NEXT:-0}` 兜住文件不存在或无匹配的情形。
注意不能写 `grep -c` 计数 —— 编号 1,3,7 时会算出 4 而非 8，造成重号。

### 章节格式

```markdown
## <N>. <本次变更的功能简述>

**背景**：<解决了什么问题>

| # | 操作步骤 | 预期结果 |
|---|----------|----------|
| 1 | <步骤> | <预期> |
| 2 | <步骤> | <预期> |
```

---

## 步骤二：Amend Commit + Force Push

⚠️ **不要用 `git add -u`。** 它会把工作区**所有**已跟踪文件的改动纳入 amend，
若用户手头还有与本 MR 无关的改动，会被静默塞进 force push 到远端 —— 这类污染事后
无法从提交历史里区分，因为它和本次改动混在同一个 commit 里。

先列出待提交内容并确认范围：

```bash
git status --porcelain
```

| 情况 | 动作 |
|------|------|
| 只有本次任务改动的文件 | 按路径显式 stage |
| 存在无关改动 | **停下问用户**：一起提交、还是先 stash 无关改动 |
| 有未跟踪文件（`??`） | 逐个确认是否该纳入，不要盲目 `git add .` |

确认后按路径显式添加：

```bash
# 只 stage 本次真正改动的文件，逐个写路径
git add path/to/changed1.go path/to/changed2.go
git add "$DOC"                 # 测试文档（$DOC 见步骤一）

git diff --cached --stat        # 复核 staged 内容与预期一致
git commit --amend --no-edit
git push --force-with-lease
```

- `--force-with-lease` 失败 → 中断，提示 `git pull --rebase` 后重试
- 不使用 `--force`，保护远端他人提交

---

## 步骤三：更新 MR 描述

### 3.1 规则

- **仅改写 `## Summary` 区块**，其他区块（Checklist、Reviewer Notes 等）不动
- 若无 `## Summary` → 在末尾追加
- 若已有 → **重新提炼**，不是往末尾追加一条
- 顺带检查描述中过期信息（如"依赖 xx MR 尚未合并"但已合并），就地更正

### 3.2 Summary 写作规范

面向 **TPM / 产品经理**，读完能直接写发版公告。

#### 核心：每次重新提炼，不越攒越长

同一 MR 会被 sync 多次。每次都追加一条最后攒成几十条碎片 → TPM 看不懂。

正确做法：

1. **开头一句话**概括本次发布主线
2. **按用户感知的功能域分组**（不按文件/代码位置）
3. 每组 ≤5 条，超了说明可以再合并

#### 提炼原则

| 原则 | 示例 |
|------|------|
| 按结果写，不按代码位置 | 「列表加列」+「详情补字段」= 一条「能看懂触发规则」 |
| 合并同类细节 | 折行/截断/漏译等 → 「其他体验优化」 |
| 去掉内部取舍 | 「xx 能力走后端不提供」是决策，不是发版信息 |
| 去掉跨仓库依赖 | 开发协作信息不该出现在发版 Summary |
| 保留影响范围提示 | 涉及生产的改动写清边界 |

#### 条目写法

```
- **用户得到了什么**：具体描述。必要时补"此前是什么样"让读者感知差异。
```

**禁止**：
- ❌ 技术实现细节（`invalidatesTags`、`useMemo`）
- ❌ 文件名/函数名/字段名作标题
- ❌ 开发术语（竞态条件、缓存失效、subscription 泄漏）

**验收标准**：Summary 直接发给 TPM，对方不追问就能写发版公告。

#### 原有细节保留

提炼会丢信息，reviewer/测试需逐项对照。把原 Summary 逐条内容搬到：

```markdown
## 改动明细（开发 / 测试参考）

> 面向 reviewer 与测试的逐项记录；发版信息请看上方 Summary。

<原逐条内容，一条不删>
```

后续 sync：新改动追加到「改动明细」+ 重新提炼 Summary。

### 3.3 执行 —— 描述必须走文件，不要内联

**不要**把描述直接拼进命令行。MR 描述里常出现反引号包裹的命令、`$(...)`、`${VAR}`
—— shell 会在传给 glab **之前就把它们展开**，导致描述被静默篡改（写 `` `hostname` ``
最后变成主机名）。这不是注入，是更难发现的内容损坏。

正确做法：**引号 heredoc**（`<<'EOF'`，单引号关闭所有展开）写入临时文件，再整体传入：

```bash
DESC_FILE=$(mktemp)
cat > "$DESC_FILE" <<'EOF'
## Summary

- **能看懂流水线什么时候会跑**：列表和详情新增「触发规则」，用 `推送 master` 这类
  说法代替原先的表达式。

## 改动明细（开发 / 测试参考）

<逐条内容>
EOF

# 双引号包裹命令替换：内容作为单个参数传入，不会被再次解析
glab mr update "$IID" --description "$(cat "$DESC_FILE")"
rm -f "$DESC_FILE"
```

要点：
- heredoc 定界符**必须加单引号** `<<'EOF'`。写成 `<<EOF` 则内容仍会被展开
- `"$(cat "$DESC_FILE")"` 的双引号不可省，否则换行会被折叠、`*` 会被通配展开
- 描述超长触发 `ARG_MAX` 时改用 API，**注意必须是 `-F` 而不是 `-f`**：

```bash
glab api --method PUT "projects/:fullpath/merge_requests/$IID" \
  -F description=@"$DESC_FILE"
```

> ⚠️ `-f/--raw-field` 是**纯字符串**，不展开 `@` —— 写成 `-f description=@file`
> 会把字面量 `@file` 存成描述内容。这个错误在本 skill v1.2.1 里真实存在过，
> 实测时把一个 MR 的描述整段替换成了 `@/tmp/desc_before.md`。
> `@` 展开属于 `-F/--field`（已用可撤销的评论创建 + 删除验证过）。

---

## 边界场景

| 场景 | 处理 |
|------|------|
| 保护分支 | 中断 |
| 无变更 | 中断 |
| 无 opened MR | 提示先创建 |
| glab 不存在 | 提示 `brew install glab` |
| force push 失败 | 提示 rebase |
| 测试文档目录不存在 | 自动创建 |
| Summary 已攒成长列表 | 重新提炼，原内容搬到「改动明细」 |
| 描述中过期信息 | 就地更正并说明 |
| `find` 命中多个 `test-plan-mr-*.md` 目录 | 取排序后第一个，并在回复中说明选了哪个 |
| 同分支存在多个 opened MR | 取第一条；用户显式指定编号时优先用用户的 |
| 描述含反引号 / `$(...)` / `${VAR}` | 必须走引号 heredoc + 文件传参（见 3.3） |
| 描述超长触发 `ARG_MAX` | 改用 `glab api --method PUT ... -F description=@文件`（必须 `-F`，`-f` 不展开 `@`） |

---

## 写入命令前的四问

本 skill 的命令会被 agent 直接执行，出错代价高（force push、改 MR 描述都影响远端）。
新增或修改任何命令前先过这四问 —— 都只在特定条件下暴露，单次顺利执行证明不了什么：

| 四问 | 对应缺陷 | 本 skill 真实踩过的坑 |
|------|---------|---------------------|
| **换个环境还成立吗？** | 可移植性 | `xargs` 对空输入的处理 BSD 与 GNU 不一致，原路径发现依赖了它（v1.1.0 修） |
| **跑第二遍会怎样？** | 幂等性 | 测试文档章节编号需读取现有最大值后 +1，否则重复执行会覆盖或错号。<br>另注意"判存在"本身也会踩坑：`[ -e X ]` 会跟随符号链接，对**悬空** symlink 返回 false，须写 `[ -e X ] \|\| [ -L X ]`（v1.2.1 补） |
| **输入为空会怎样？** | 边界输入 | `find` 无命中时 `dirname` 参数为空，可能把测试文档写进项目根目录（v1.1.0 修） |
| **变量还活着吗？** | 变量作用域 | agent 每步开新 shell，前置检查设的 `$IID` 到步骤二就没了。空值下 `glab mr update ""` 可能打到错误目标。用前必须 `: "${IID:?}"` 校验，或重新派生（v1.3.0 修） |

答不上来就就地验证：**在临时目录跑一遍、连跑两遍、喂空输入再跑一遍、换个 shell 调用再跑一遍**。
四次都符合预期才写进去。

### 验证破坏性命令时的额外纪律

本 skill 的命令会改远端状态，不能"跑一下看看"。要验证就用**可完全撤销**的等价操作：

- 验证 API 参数语法 → 创建一条评论再删除，**不要拿 MR 描述当试验品**
- 需要验证描述类写操作 → 先把原值存盘，出错才能恢复

这条来自真实事故：为验证 `-f description=@file` 是否可用，直接对真实 MR 执行，
结果该写法不展开 `@`，把整段描述替换成了字面量文件名。原值虽已恢复，但如果当时
没有及时发现、或原文无从重建，损失不可逆。

---

## Changelog

统一格式：**问题 → 修复**，便于审计每条变更的来源。

| 版本 | 问题 | 修复 |
|------|------|------|
| v1.3.0 | `git add -u` 把工作区所有已跟踪改动纳入 amend，无关改动被静默 force push 到远端，事后无法从历史中区分 | 禁用 `git add -u`；先 `git status --porcelain` 确认范围，按路径显式 stage，有无关改动时停下问用户 |
| v1.3.0 | 变量不跨 shell 调用存活。agent 每步开新 shell，`$IID` 到步骤二为空，`glab mr update ""` 可能打到错误目标 | 给出「同一 shell 连续执行」或「每步重新派生」两种用法；派生末尾加 `: "${IID:?}"` 强制校验非空 |
| v1.3.0 | 写进 skill 的 `-f description=@file` **是错的**，`-f/--raw-field` 不展开 `@`。实测时把真实 MR 描述整段替换成字面量 `@/tmp/desc_before.md` | 改为已验证的 `-F/--field`（用创建评论+删除的可撤销方式验证）；新增「验证破坏性命令时的额外纪律」 |
| v1.3.0 | 章节编号递增只有文字描述，agent 可能用计数代替取最大值，编号不连续时重号 | 补可执行片段，四种边界实测（正常 / 文件不存在 / 无编号章节 / 非连续 1,3,7→8） |
| v1.2.1 | `[ -e X ]` 跟随符号链接，对悬空链接返回 false，幂等失效 | 四问表补该案例，判存在须 `[ -e X ] \|\| [ -L X ]` |
| v1.2.0 | 缺少通用的命令自检原则 | 新增「写入命令前的三问」，与 generate-agents-md 同一套判据（v1.3.0 扩为四问） |
| v1.1.0 | 前置检查是零散片段，未定义中断行为 | 改为可执行脚本，加 `set -euo pipefail` |
| v1.1.0 | 步骤二有字面占位符 `<iid>`，照字面执行会生成名为 `test-plan-mr-<iid>.md` 的错误文件 | 改用变量（v1.3.0 进一步解决变量生命周期） |
| v1.1.0 | 路径发现依赖 `xargs`，BSD 与 GNU 对空输入行为不一致 | 去掉 `xargs`，显式判空；多匹配时排序取首并告知用户 |
| v1.1.0 | MR 描述内联传参，shell 提前展开内容里的反引号与 `$(...)`，静默篡改描述 | 改为引号 heredoc 写文件 + `"$(cat file)"` 传入 |
| v1.0.0 | — | 从 glider 的项目级 steering 抽象为通用 skill，剔除部署步骤，测试文档路径改为自动发现 |


