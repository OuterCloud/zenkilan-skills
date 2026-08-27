---
name: pptx-gen
version: 3.0.0
description: "基于指定 PPTX 模板生成专业演示：分析模板页面和精确形状，规划内容映射，包级复制幻灯片并填充，执行结构、内容和视觉 QA。当用户说生成PPT、做演示文稿、把文档做成PPT、使用指定模板时触发。"
metadata:
  requires:
    bins: [python3]
---

# pptx-gen — 专业可靠的模板优先 PPT 生成

## 不可违背的原则

<critical>
**用户提供了模板，就必须从该模板生成。严禁改走“从零创建”。**

模板是品牌规范，不是配色参考。输出页必须由模板中的源 slide 包级复制得到，保留背景、图片、母版、布局、主题、字体、装饰与关系文件；只编辑用户内容对应的形状。
</critical>

- 禁止用 `python-pptx` 模拟 duplicate slide：它不能可靠复制关系图，容易丢背景和图片。
- 禁止按旧文字模糊替换：模板常有重复占位文案，会改错位置。
- 必须使用 `shape_id` 精确编辑；旧 `replacements` 只兼容唯一匹配，歧义时必须失败。
- 不得带着 warning 交付。`--allow-warnings` 仅用于诊断，最终生成禁止使用。
- 不得遗留 `Please Enter...`、`TITLE GOES HERE`、`Sample text`、`Lorem`、`TODO` 等模板内容。
- 只有用户明确表示没有模板，并同意自由设计时，才可使用 `create_deck.js`。

## 工具与架构

```
scripts/
├── analyze_template.py  # OOXML 分析：页、shape_id、文字、位置、媒体关系、用途建议
├── fill_template.py     # 包级复制 slide + rels；按 shape_id 编辑；占位清理
├── validate_pptx.py     # ZIP/XML/关系/Content Types/媒体/占位文字检查
└── render_slides.py     # Keynote 或 LibreOffice 导出 PDF + 逐页 PNG
```

`fill_template.py` 直接操作 PPTX ZIP 包：复制 `slideN.xml` 与其 `.rels`，再更新 `presentation.xml`、`presentation.xml.rels` 和 `[Content_Types].xml`。源 slide 的关系 ID 原样保留，因此背景、图片、布局和图表不会断链。

## 前置检测

```bash
SKILL_DIR="$HOME/.kiro/skills/pptx-gen"
python3 -c "import lxml, pymupdf" 2>/dev/null || \
  python3 -m pip install -r "$SKILL_DIR/requirements.txt"
```

若当前工具不是 Kiro，将 `SKILL_DIR` 替换为本 skill 的实际目录。

## 强制工作流

### 1. 获取并理解内容

读取用户提供的 PDF、Word、Markdown 或文字。先形成演讲逻辑，再写 slide 文案：

- 明确受众、目的、主题、时长和语言。
- 20 分钟通常规划 12–18 页；宁可拆页，不把长文塞进单页。
- 每页只表达一个核心观点；标题尽量短，正文优先要点、数据、流程和对比。
- 不得编造源文档没有的数据或制度；推断内容须明确标注。

### 2. 分析模板（必须）

```bash
python3 "$SKILL_DIR/scripts/analyze_template.py" template.pptx \
  --output /tmp/template-analysis.json
```

重点读取每页：

- `source_slide`：生成数据使用的 0-based 源页索引。
- `suggested_usage`：封面、章节页、内容页、图文页等用途建议。
- `shapes[].shape_id`：唯一编辑标识。
- `shapes[].text`、`position`、`has_text_body`：现有文案、位置和可编辑性。
- `background`、`media_relation_count`：视觉和媒体复杂度。
- `text_shape_ids`：所有含文字的可编辑形状。

模板页不是最终内容，而是“版式画板”。先给每个源页标注用途，再映射内容；不要连续滥用同一版式。

### 3. 规划 slide map

生成前先建立映射表：

| 输出页 | 目的 | source_slide | 编辑 shape_id | 清理 shape_id | 预计讲述 |
|-------|------|--------------|----------------|----------------|----------|
| 1 | 封面 | 2 | 68 标题 | — | 30 秒 |
| 2 | 议程 | 3 | 68、67、40、53、54、55 | 其余示例框 | 1 分钟 |

规则：

1. 选择容纳能力与内容相匹配的模板页，不能把 6 个要点塞进只容纳 2 项的版式。
2. 每个模板示例文本形状必须：填充、清空，或明确保留为品牌固定文字。
3. 只有确定为品牌固定文字的 shape 才能不动；不要误清 logo、页脚或版权文字。
4. 文字比原框容量明显更长时，缩短文案或换版式，不依赖自动缩小字体救场。

### 4. 生成严格 data.json

```json
{
  "forbidden_text_patterns": ["自定义占位词"],
  "slides": [
    {
      "source_slide": 2,
      "editable_shape_ids": [68],
      "require_all_edits": true,
      "edits": [
        {"shape_id": 68, "text": "The Role of the Homeroom Teacher\n班主任的角色"}
      ]
    },
    {
      "source_slide": 3,
      "editable_shape_ids": [67, 68, 40, 53, 54, 55],
      "require_all_edits": true,
      "edits": [
        {"shape_id": 68, "text": "Agenda 议程"},
        {"shape_id": 67, "text": "20-Minute Overview"},
        {"shape_id": 40, "text": "Vision 愿景"},
        {"shape_id": 53, "text": "Roles 角色"},
        {"shape_id": 54, "text": "Responsibilities 职责"},
        {"shape_id": 55, "text": "Expectations 要求"}
      ]
    },
    {
      "source_slide": 13,
      "editable_shape_ids": [24, 33, 34, 35, 36],
      "require_all_edits": true,
      "edits": [
        {"shape_id": 24, "text": "Four Priorities 四项重点"},
        {"shape_id": 33, "paragraphs": [
          {"text": "01  Student Care 学生关怀", "bold": true, "size": 18},
          {"text": "Know every learner and respond early.", "size": 12}
        ]}
      ],
      "clear_shape_ids": [34, 35, 36]
    }
  ]
}
```

#### 数据契约

- `source_slide`：必填；来自分析结果，0-based。
- `edits[].shape_id`：必填；只能使用该源页实际存在的 ID。
- `text`：换行会生成多个段落并继承原样式。
- `paragraphs`：支持 `text`、`bold`、`size`、`color`、`alignment`、`level`。
- `clear_shape_ids`：清除不用的模板文本框，但保留形状与视觉结构。
- `editable_shape_ids` + `require_all_edits: true`：确保应处理的形状没有遗漏。
- `forbidden_text_patterns`：在内置占位词之外追加项目特定禁词。

不要把 `replacements` 作为主方案。它仅为旧数据兼容，匹配 0 次或多次会失败。

### 5. 严格生成

```bash
python3 "$SKILL_DIR/scripts/fill_template.py" \
  --template template.pptx \
  --data /tmp/deck-data.json \
  --output output.pptx
```

若失败，修正 data.json；禁止通过 `--allow-warnings` 绕过。

### 6. 结构 QA（必须）

```bash
python3 "$SKILL_DIR/scripts/validate_pptx.py" output.pptx \
  --template template.pptx --json
```

交付门槛：

- `valid: true`，`errors` 为空。
- ZIP CRC、XML、slide relationship、媒体目标和 Content Types 完整。
- 输出引用的 slide 数与规划一致。
- 模板媒体 parts 没有丢失。

### 7. 内容 QA（必须）

```bash
python3 -m markitdown output.pptx > /tmp/output-content.md
```

逐页核对：标题、顺序、数字、双语、遗漏、错别字。再查占位内容：

```bash
grep -niE 'Please Enter|Enter your subhead|TITLE GOES HERE|sample text|lorem|TODO|click to edit' \
  /tmp/output-content.md && exit 1 || true
```

若没有 `markitdown`，用分析器读取输出页文字，并与 data.json 对照。

### 8. 视觉 QA（必须）

```bash
python3 "$SKILL_DIR/scripts/render_slides.py" output.pptx \
  --output-dir /tmp/output-render
```

逐张查看 `/tmp/output-render/slide-*.png`，至少检查：

- 背景、logo、图片和装饰是否完整。
- 文本是否溢出、截断、重叠或错位。
- 模板占位物是否遗留。
- 字号、对齐、行距、留白和层级是否一致。
- 中英文换行是否自然，标点与大小写是否正确。
- 内容是否落入正确语义区域，而非只“替换成功”。

发现问题后修改 data.json，重新生成、验证、渲染。至少完成一次“生成 → 渲染 → 检查”闭环；有问题必须迭代到无明显缺陷。

## 最终交付清单

- [ ] 所有输出页来自用户指定模板。
- [ ] 使用 `shape_id` 精确编辑，没有歧义文字替换。
- [ ] 每个模板示例文本框已填充或清空。
- [ ] 结构验证通过，无关系断链、背景/媒体丢失。
- [ ] 内容验证通过，无占位词、遗漏和错误顺序。
- [ ] 每页完成视觉检查，无溢出、重叠和错位。
- [ ] 返回输出文件路径、页数、内容摘要和 QA 结果。

## 无模板时的例外

只有用户明确没有模板并同意自由设计时，才可使用：

```bash
node "$SKILL_DIR/scripts/create_deck.js" config.json
```

若用户只是暂未上传模板，先索要模板，不得擅自从零创建。
