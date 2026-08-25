---
name: pptx-gen
version: 1.0.0
description: "基于模板生成专业 PPT：分析模板结构、规划内容映射、自动填充生成。当用户说'生成PPT'、'做个演示文稿'、'把这个内容做成PPT'、'用模板生成幻灯片'时触发。"
metadata:
  requires:
    bins: [python3, node]
---

# pptx-gen — 自动生成专业 PPT

## 适用范围

| 场景 | 路径 | 说明 |
|------|------|------|
| 有模板 .pptx | 主路径：模板填充 | 分析模板 → 规划内容 → JSON 数据 → 填充生成 |
| 无模板 | 备用路径：从零创建 | 用 PptxGenJS 生成带专业样式的幻灯片 |

触发关键词：`生成PPT`、`做个演示文稿`、`把这个内容做成PPT`、`用模板生成幻灯片`、`做PPT`

## 前置检测

在执行任何生成操作前，先确认依赖已就绪：

```bash
# 检查 python-pptx（模板填充路径必需）
python3 -c "import pptx; print('python-pptx', pptx.__version__)" 2>/dev/null || \
  pip3 install -r ~/.kiro/skills/pptx-gen/requirements.txt

# 检查 pptxgenjs（从零创建路径必需）
node -e "require('pptxgenjs')" 2>/dev/null || \
  npm install --prefix ~/.kiro/skills/pptx-gen
```

如果 pip3/npm 均不可用，提示用户手动安装。

## 核心流程 — 基于模板生成（主路径）

当用户提供了 .pptx 模板文件时使用此流程。

### Step 1: 分析模板

```bash
python3 ~/.kiro/skills/pptx-gen/scripts/analyze_template.py <template.pptx>
```

输出 JSON 包含：
- `layouts[]` — 所有可用版式，每个 layout 包含 name 和 placeholders 列表
- `existing_slides[]` — 模板中已有的幻灯片及其内容摘要
- 每个 placeholder 包含：`idx`（索引号）、`name`、`type`（title/body/picture/object 等）、`position`（位置尺寸）

**重点关注**：记住每个 layout 的 name 和它包含的 placeholder idx，后续步骤需要用到。

### Step 2: 规划内容映射

根据用户提供的内容（文档、文字、大纲），做以下规划：

1. **拆分内容为若干 slides** — 每张 slide 一个核心观点
2. **为每张 slide 选择 layout** — 从 Step 1 分析结果中挑选合适的版式名称
3. **决定每个 placeholder 填什么** — 将内容分配到对应 idx 的 placeholder

如果模板中已有幻灯片样式很好，可以使用 `duplicate_from` 复制已有 slide 并修改内容。

### Step 3: 生成 data.json

按下方「data.json 格式参考」生成数据文件，保存到工作目录。

### Step 4: 填充生成

```bash
python3 ~/.kiro/skills/pptx-gen/scripts/fill_template.py \
  --template <模板.pptx> \
  --data <data.json> \
  --output <输出.pptx>
```

**参数说明**：
- `--template`：模板文件路径
- `--data`：Step 3 生成的 JSON 数据文件
- `--output`：输出文件路径
- `--keep-template-slides`：可选，保留模板原有幻灯片（默认移除）

脚本会逐 slide 处理并输出进度到 stderr。

### Step 5: 验证

生成后用 markitdown 提取文本，确认内容填充正确：

```bash
markitdown <输出.pptx>
```

检查要点：
- 所有 slide 标题是否正确
- 内容是否完整、无遗漏
- 顺序是否符合预期

## 备用流程 — 从零创建（无模板时）

当用户没有模板文件时，使用 PptxGenJS 从零创建带专业样式的演示文稿。

```bash
node ~/.kiro/skills/pptx-gen/scripts/create_deck.js <config.json> [output.pptx]
```

第二个参数为可选的输出路径，默认使用 config.json 中 `output` 字段或 `output.pptx`。

### config.json 格式

```json
{
  "theme": {
    "primary_color": "2F5496",
    "secondary_color": "4472C4",
    "accent_color": "ED7D31",
    "background_color": "FFFFFF",
    "text_color": "333333",
    "light_text_color": "666666",
    "font_heading": "Microsoft YaHei",
    "font_body": "Microsoft YaHei"
  },
  "metadata": {
    "title": "演示文稿标题",
    "author": "作者",
    "subject": "主题"
  },
  "output": "output.pptx",
  "slides": [
    {"type": "cover", "title": "主标题", "subtitle": "副标题", "date": "2024-01-01"},
    {"type": "section", "title": "章节标题", "subtitle": "章节描述"},
    {"type": "content", "title": "要点页", "bullets": ["要点1", "要点2", "要点3"]},
    {"type": "content", "title": "表格页", "table": {"headers": ["列A","列B"], "rows": [["1","2"]]}},
    {"type": "content", "title": "双栏页", "columns": [
      {"title": "左栏", "bullets": ["左1", "左2"]},
      {"title": "右栏", "bullets": ["右1", "右2"]}
    ]},
    {"type": "content", "title": "文本页", "text": "一段详细文字说明..."},
    {"type": "summary", "title": "总结", "bullets": ["结论1", "结论2"], "closing": "谢谢！"}
  ]
}
```

### Slide 类型说明

| type | 说明 | 支持字段 |
|------|------|---------|
| `cover` | 封面页（深色背景 + 大标题） | title, subtitle, date |
| `section` | 章节分隔页 | title, subtitle |
| `content` | 正文内容页 | title, 以及 bullets / table / columns / text 四选一 |
| `summary` | 总结页（带✓标记） | title, bullets, closing |

### bullets 嵌套层级

bullets 支持字符串或带层级的对象：

```json
["普通要点", {"text": "子要点", "level": 1}]
```

### theme 字段

所有颜色为 6 位 hex（不带 #）。`theme` 整个可省略，使用默认蓝色主题。

## data.json 格式参考（模板填充路径）

```json
{
  "slides": [
    {
      "layout": "Title Slide",
      "placeholders": {
        "0": {"type": "text", "content": "演示标题"},
        "1": {"type": "text", "content": "副标题内容"}
      }
    },
    {
      "duplicate_from": 0,
      "placeholders": {
        "0": {"type": "text", "content": "基于第一张slide复制，替换标题"}
      }
    },
    {
      "layout": "Title and Content",
      "placeholders": {
        "0": {"type": "text", "content": "章节标题"},
        "1": {"type": "text", "content": "第一行\n第二行\n第三行"}
      }
    },
    {
      "layout": "Two Content",
      "placeholders": {
        "0": {"type": "text", "content": "对比分析"},
        "1": {"type": "table", "content": {
          "headers": ["指标", "今年", "去年"],
          "rows": [["营收", "100M", "80M"], ["利润", "20M", "15M"]]
        }},
        "2": {"type": "image", "content": "/path/to/chart.png"}
      }
    }
  ]
}
```

### 字段定义

**每个 slide 对象**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `layout` | string | 版式名称（与 analyze_template 输出的 layout name 一致），和 duplicate_from 二选一 |
| `duplicate_from` | number | 复制模板中已有 slide 的索引（0-based），和 layout 二选一 |
| `placeholders` | object | key 为 placeholder idx（字符串），value 为内容描述对象 |

**placeholder 内容对象**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | `"text"` / `"table"` / `"image"` |
| `content` | 见下 | 根据 type 不同格式不同 |

**content 格式**：

- `type: "text"` → content 为字符串（支持 `\n` 换行）或富文本数组
- `type: "table"` → content 为 `{"headers": [...], "rows": [[...], ...]}`
- `type: "image"` → content 为图片本地路径字符串

### 富文本格式（text 类型的 content 为数组时）

```json
[
  {"text": "加粗大标题", "bold": true, "size": 28, "color": "2F5496", "align": "center"},
  {"text": "普通正文段落", "size": 14},
  {"text": "红色强调", "bold": true, "color": "FF0000", "italic": true}
]
```

每个段落对象支持的属性：

| 属性 | 类型 | 说明 |
|------|------|------|
| `text` | string | 段落文本内容（必填） |
| `bold` | boolean | 加粗 |
| `italic` | boolean | 斜体 |
| `size` | number | 字号（pt） |
| `color` | string | 字色，6位hex |
| `font_name` | string | 字体名称 |
| `align` | string | 对齐：left / center / right / justify |
| `space_before` | number | 段前间距（pt） |
| `space_after` | number | 段后间距（pt） |

## 内容规划最佳实践

在 Step 2 规划内容映射时，遵循以下原则：

1. **不要把所有内容塞到一张 slide** — 信息过载会降低表达效果
2. **标题简洁（< 10 字）** — 用名词或短语，不用完整句子
3. **内容要点化** — bullet points 优于大段文字，每条 bullet ≤ 25 字
4. **变换 layout** — 交替使用不同版式，避免视觉单调
5. **每张 slide 一个核心观点** — 观众一眼能抓住重点
6. **图表优先于纯文字** — 有数据时用 table，有对比时用双栏
7. **动态决定 slide 数量** — 一般 10-20 页。内容少则精简，内容多则合理拆分
8. **结构化呈现** — 开头封面 → 目录/章节 → 正文 → 总结

## 典型用法示例

### 示例 1：从一篇文档生成 PPT

```
用户：把这篇文档做成PPT，用这个模板 company_template.pptx
```

执行步骤：
1. 读取文档内容，提取核心观点和结构
2. `python3 ~/.kiro/skills/pptx-gen/scripts/analyze_template.py company_template.pptx`
3. 根据文档结构和模板版式，规划 slides 内容映射
4. 生成 data.json
5. `python3 ~/.kiro/skills/pptx-gen/scripts/fill_template.py --template company_template.pptx --data data.json --output output.pptx`
6. `markitdown output.pptx` 验证

### 示例 2：从一段文字大纲生成 PPT（无模板）

```
用户：帮我做个项目汇报PPT，内容是：1. 项目背景 2. 进展 3. 风险 4. 下一步
```

执行步骤：
1. 根据大纲构建 config.json，选择合适的 slide 类型
2. 生成 config.json（cover + section + content slides + summary）
3. `node ~/.kiro/skills/pptx-gen/scripts/create_deck.js config.json output.pptx`
4. `markitdown output.pptx` 验证

### 示例 3：指定模板 + 内容文件批量生成

```
用户：用 template.pptx 模板，把 report.md 的内容生成PPT
```

执行步骤：
1. 读取 report.md 提取结构化内容
2. 分析 template.pptx 获取可用 layouts
3. 将 markdown 各章节映射到 slides，选择对应 layout
4. 生成 data.json 并填充生成
5. 验证输出

## 已知限制

- **SmartArt 不支持** — python-pptx 无法创建或编辑 SmartArt 图形
- **复杂动画不支持** — 无法添加转场动画或自定义动画效果
- **duplicate_slide 兼容性** — 通过 XML 深拷贝实现，极个别含 OLE 嵌入对象或复杂母版关联的模板可能有兼容问题
- **图片必须为本地路径** — 不支持 URL，如需远程图片需先下载到本地
- **表格样式有限** — 填充模板中的表格使用 insert_table，样式继承自模板定义
- **从零创建不支持图片** — create_deck.js 当前只支持文本、表格、分栏内容
