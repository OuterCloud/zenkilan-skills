---
name: feishu-project-collab
version: 1.0.0
description: "飞书项目（Feishu Project / Meego）协作：通过飞书项目 MCP 查询与流转研发工作项（需求 story / 缺陷 issue / 任务 sub_task），形成「缺陷发现 → 处理 → 修复回填 → 流转解决」的自闭环。当用户需要查/改飞书项目的工作项、缺陷单、需求、状态流转、评论回填、排期/计划表(WBS)时使用。不负责：飞书云文档（feishu-doc-collab）、飞书消息（lark-im）、日历（lark-calendar）、审批（lark-approval）、多维表格（lark-base）。飞书项目 ≠ 飞书开放平台，二者 MCP 不同。"
metadata:
  requires:
    bins: [curl]
---

# 飞书项目协作（Feishu Project / Meego）

你具备通过**飞书项目 MCP**（Meego MCP Server）查询与流转研发工作项的能力。当用户需要围绕飞书项目的缺陷单 / 需求 / 任务做协作与状态驱动时，按本规则执行。

> **⚠️ 关键区分**：飞书项目（`project.feishu.cn`，内部代号 **Meego**）是独立于飞书开放平台（`open.feishu.cn`）的产品，**MCP 完全不同**。
> - 飞书**文档/IM/多维表格** → 用 `feishu-doc-collab` / `lark-*`（连 `mcp.feishu.cn` 或 `open.feishu.cn`）。
> - 飞书**项目工作项/缺陷/需求** → 用本 skill（连 `project.feishu.cn/mcp_server/v1`）。

## 适用范围

| 适用 ✅ | 不适用 ❌ |
|---------|-----------|
| 查缺陷/需求/任务列表与详情 | 飞书云文档读写 → `feishu-doc-collab` |
| 缺陷状态流转（处理中 / 已修复 / 已解决 / 关闭） | 飞书消息收发 → `lark-im` |
| 工作项评论回填（如贴 MR 链接） | 日历/会议 → `lark-calendar` |
| 创建/更新工作项字段 | 审批流程 → `lark-approval` |
| 节点流转、计划表(WBS)、排期、视图 | 多维表格/Base → `lark-base` |

**Agent 路由判断**：用户意图涉及「飞书项目 / Meego / 工作项 / 缺陷单 / 需求 / 迭代 / 排期 / 节点流转」时命中本 skill；涉及飞书文档、消息、日历、表格时转交对应 skill。

---

## 环境检测

每次触发飞书项目相关意图时，先确认飞书项目 MCP 工具可用：

1. 尝试调用 `search_project_info`（无参可调，返回最近访问的空间）
2. 工具可用且返回正常 → 进入协作场景
3. 工具不可用（找不到工具） → 输出「MCP 未配置」引导后停止
4. 工具可用但返回认证/权限错误（token 失效、`unauthorized`、HTTP 401/403、`ErrPermission` 等） → 输出「Token 引导」后停止

### 工具不可用 — MCP 未配置

```
飞书项目 MCP 未配置。这是空间级内置能力，无需自建插件。步骤：

1. 打开飞书项目 → 左侧「更多」→「MCP 配置」
   （或空间设置里搜索 MCP）
2. 打开「MCP Server」开关；「数据授权范围」勾选：
   ✅ 允许查看数据信息   ✅ 允许创建或修改数据信息
3. 「连接 MCP」选「HTTP Header」tab → 复制 Token（形如 m-xxxxxxxx-...）
4. 写入 MCP 配置文件（注意 header 名是 X-Mcp-Token，不是 Authorization）：

   {
     "mcpServers": {
       "feishu-project": {
         "url": "https://project.feishu.cn/mcp_server/v1",
         "headers": { "X-Mcp-Token": "<你的 Token>" }
       }
     }
   }

   配置文件位置：
   • Kiro:        ~/.kiro/settings/mcp.json
   • Claude Code: ~/.claude.json
   • Cursor:      .cursor/mcp.json
   • Windsurf:    ~/.codeium/windsurf/mcp_config.json

5. 保存后热重载 / 重启工具，然后重试。
```

> 也支持 **HTTP OAuth**（同页 URL `https://project.feishu.cn/mcp_server/v1`，一键授权，无需 token）与 **Stdio**（`npx -y @lark-project/meegle@latest install`）。**HTTP Header + 固定 Token 最适合自动化固定身份**，推荐首选。传输为 **Streamable HTTP**。

### 工具可用但 Token 失效

```
飞书项目 MCP Token 已失效或权限不足。请：
1. 回到飞书项目「MCP 配置」页
2. HTTP Header tab →「重置 Token」，复制新 Token 更新到 MCP 配置的 X-Mcp-Token
3. 确认「数据授权范围」两项都勾选（查看 + 创建/修改）
4. 保存后重试
```

---

## 核心概念（调用前必懂）

| 概念 | 说明 | 怎么拿 |
|------|------|--------|
| **project_key** | 空间标识 | `search_project_info` 传空间名（如「你的空间名」）即可换到 project_key；多数工具也直接接受空间名 |
| **work_item_type** | 工作项类型 key | `list_workitem_types`。常见：需求=`story`、**缺陷=`issue`**、任务=`sub_task`、版本=`version`、迭代=`sprint` |
| **work_item_id** | 工作项实例 ID | 查询结果里返回；或用户给的 URL 里解析 |
| **字段 field_key vs label** | 字段有 key（`owner`）和中文 label（`创建者`） | `list_workitem_field_config`（**参数名是 `work_item_type`，不是 `work_item_type_key`**） |
| **状态流 vs 节点流** | 缺陷(issue)是**状态流**工作项（用 `transition_state`）；含流程节点的（需求等）用 `transition_node` | 见「流转」 |
| **userKey** | 人员唯一标识 | `search_user_info`，支持传 `current_login_user()` 拿「我」 |

---

## 协作场景（缺陷闭环为主线）

### 场景 1: 定位空间

**触发**：用户提到某空间名（如「XX 空间下…」）。
1. `search_project_info` 传空间名 → 拿 project_key（或直接把空间名透传给后续工具）。

### 场景 2: 查「我的缺陷 / 工作项」

**触发**："我的缺陷"、"待我处理的缺陷"、"XX 空间下的缺陷列表"。

两条路，按精确度选：
- **`list_todo`**（推荐查「我的待办/已办」）：`action=todo|done|overdue|this_week`。返回当前用户相关工作项（含缺陷），无需写 MQL，最省事。缺点：不按单一类型过滤。
- **`search_by_mql`**（推荐按类型 + 条件精确查）：写 MQL 查特定类型。

先用 `search_user_info(["current_login_user()"])` 拿到自己的 **userKey + 显示名**（后面 MQL 用户过滤要用，见坑 ②）。

### 场景 3: 看缺陷详情 + 评论

1. `get_workitem_brief`（按 id 或 name 查概况；要全量自定义字段先 `list_workitem_field_config` 拿 field_keys 再传 `fields`）。
2. `get_node_detail`（看节点/子任务，若该类型有流程）。
3. `list_workitem_comments`（看历史评论/反馈）。

### 场景 4: 修复回填（评论 + 字段）

1. 修复代码 / 推 MR 后，`add_comment` 在缺陷单回填说明与 **MR 链接**（content 用 markdown，超链接 `[标题](url)`；@人需先 `search_user_info` 拿 lark_user_id 拼 mention 格式）。
2. 需要改字段（如指派、严重程度）→ `update_field`。

### 场景 5: 流转到「已解决 / 关闭」

**缺陷(issue)是状态流工作项**：
1. `get_transitable_states`（传 work_item_id + project_key + work_item_type=issue）→ 拿当前可流转到的目标状态与 **transition_id**。
2. `transition_state`（传 transition_id）执行流转。
3. （若流转需必填项，先 `get_transition_required` 补齐）。

**若是节点流工作项**（如需求走流程节点）：用 `transition_node`（confirm 流转 / rollback 回退）+ `get_node_detail` 定位 node_id。

---

## ⚠️ 踩坑经验（务必遵守，都是实测踩过的）

1. **MQL 字段名必须用该空间实际字段的 label，别用直觉名**。先 `list_workitem_field_config`（参数 `work_item_type`）拿准确字段。实测「缺陷」类型常见映射：
   - `标题` ❌ → **`缺陷名称`**（key `name`）
   - `状态` ❌ → **`缺陷状态`**（key `work_item_status`）
   - `创建人` ❌ → **`创建者`**（key `owner`，user 类型）
   - `负责人` ❌（不存在）→ **`当前负责人`**（key `current_status_operator`，multi-user）
   - `优先级`=`priority`、`严重程度`=`severity`、`更新人`=`updated_by`
   - MQL 的 SELECT/WHERE 用 **label**（反引号包裹），FROM 用 `` `空间名`.`类型名` ``（如 `` `你的空间名`.`缺陷` ``）。

2. **MQL 里的「用户值」不能写 `current_login_user()`**（那只在 `search_user_info` 里有效）。用户字段过滤要用**精确显示名**或 **`X<id:userKey>`** 形式：
   - 先 `search_user_info(["current_login_user()"])` 拿到自己的 userKey 和 name_cn；
   - MQL 里写 `` WHERE `创建者` = '张三' `` 或 `` = '<id:7xxxxxxxxxxxxxxxxxx>' ``。
   - 报错 `user 'xxx' does not exist` 就是这个原因。

3. **`list_workitem_field_config` 的参数是 `work_item_type`**（值如 `issue`），不是 `work_item_type_key`；传错会报 `argument arguments.work_item_type is required`。

4. **MQL 报 `attribute label not found` 时，错误信息会给出 `did you mean 'xxx'`**——直接按提示改字段名重试即可，不用瞎猜。空结果 ≠ 报错，查询无报错即成功。

5. **区分状态流 / 节点流**：缺陷(issue)→ `get_transitable_states` + `transition_state`；需求等带流程节点 → `transition_node`。搞反会找不到可流转项。

6. **写操作以配置的身份执行并留痕**（X-Mcp-Token / userKey 对应的用户）。给自动化用建议专门的身份账号，且该账号在目标空间有相应权限，否则服务端返回权限错误。

---

## 工具速查

| 分类 | 工具 | 用途 |
|------|------|------|
| 空间/人员 | `search_project_info` | 空间名 → project_key / 验证空间 |
| | `search_user_info` | 姓名/邮箱/`current_login_user()` → userKey |
| | `list_project_team` / `list_team_members` | 团队与成员 |
| 元数据 | `list_workitem_types` | 空间下工作项类型（issue/story/sub_task…） |
| | `list_workitem_field_config` | 字段 key/label/类型（参数 `work_item_type`） |
| | `list_workitem_role_config` | 角色配置 |
| 查询 | `search_by_mql` | MQL 精确查工作项（按类型+条件） |
| | `list_todo` | 我的待办/已办（含缺陷），免写 MQL |
| | `get_workitem_brief` | 工作项概况（可传 fields 拿全字段） |
| | `get_node_detail` | 节点/子任务详情 |
| | `list_workitem_relations` / `list_related_workitem` | 关联关系 |
| | `list_schedule` | 人员排期/工时 |
| 写入 | `create_workitem` | 建工作项（template 必传，先查 field/role config） |
| | `update_field` | 改字段/角色 |
| | `update_node` / `update_node_subtask` | 改节点/子任务 |
| 流转 | `get_transitable_states` → `transition_state` | 状态流工作项（缺陷）流转 |
| | `get_transition_required` | 流转必填项 |
| | `transition_node` | 节点流转/回退 |
| 评论/附件 | `add_comment` | 加评论（markdown，可 @人/超链接/附件） |
| | `list_workitem_comments` | 评论列表 |
| | `upload_file` / `get_download_url` | 附件上传/下载 |
| 计划表(WBS) | `create_wbs_draft` / `edit_wbs_draft` / `list_wbs_draft_rows` / `publish_wbs_draft` / `reset_wbs_draft` | 计划表草稿编辑与发布 |
| 视图/度量 | `get_view_detail` / `search_view_by_title` / `list_charts` / `get_chart_detail` | 视图与图表 |

> 完整工具约 47 个，以 MCP `tools/list` 返回为准；上表为闭环常用项。

---

## 缺陷自闭环（标准流程）

```
1. 定位空间        search_project_info（空间名 → project_key）
2. 拿身份/类型     search_user_info(current_login_user())、list_workitem_types
3. 查缺陷          list_todo(action=todo)  或  search_by_mql（按坑①②写对字段/用户）
4. 看详情/评论     get_workitem_brief、list_workitem_comments
5. 修复            （在代码仓库定位并修复、推 MR —— 配合 sync-mr skill）
6. 回填            add_comment（贴 MR 链接与修复说明）；必要时 update_field
7. 流转已修复      get_transitable_states → transition_state
8. 验证通过 → 流转「已解决/关闭」
```

---

## 调试：用 curl 直连验证（MCP 连不通时排障）

飞书项目 MCP 是 Streamable HTTP + JSON-RPC，可绕过客户端直接验证 Token 与工具：

```bash
URL="https://project.feishu.cn/mcp_server/v1"; TOK="<你的X-Mcp-Token>"
# 1) initialize（拿 mcp-session-id）
curl -s -D- -X POST "$URL" -H "X-Mcp-Token: $TOK" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cli","version":"1.0"}}}'
# 响应头里取 mcp-session-id: xxx
# 2) tools/list（带 Mcp-Session-Id）
curl -s -X POST "$URL" -H "X-Mcp-Token: $TOK" -H "Mcp-Session-Id: <sid>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
# 3) tools/call
curl -s -X POST "$URL" -H "X-Mcp-Token: $TOK" -H "Mcp-Session-Id: <sid>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_project_info","arguments":{}}}'
```

- `initialize` 返回 `serverInfo.name = "Meego MCP Server"` 即 Token 有效。
- 工具结果在 `result.content[0].text`（通常是 JSON 字符串，需再 parse）。

---

## 协作最佳实践

- **先查后改**：流转前先 `get_transitable_states` 确认合法目标，避免非法流转报错。
- **留痕**：修复后务必 `add_comment` 回填 MR 链接与结论，形成可追溯闭环。
- **字段严格匹配**：`list_workitem_field_config` 先行，别用相似字段（如把「关联缺陷」当「硬件缺陷」）。
- **空结果不慌**：MQL 无报错即成功，数据为空是正常结果，不要反复改 MQL。
- **身份可见**：所有写操作记在 Token 对应用户名下，选对自动化身份。
