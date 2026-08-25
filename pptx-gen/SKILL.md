---
name: pptx-gen
version: 2.0.0
description: "基于模板生成专业 PPT：分析模板结构、规划内容映射、自动填充生成。当用户说'生成PPT'、'做个演示文稿'、'把这个内容做成PPT'、'用模板生成幻灯片'时触发。"
metadata:
  requires:
    bins: [python3, node]
---

# pptx-gen — 基于模板生成专业 PPT

## 核心原则（必须遵守）

**永远使用模板。** 模板存在的意义是保持品牌一致性（学校/公司规定用指定模板）。生成 PPT 时：

1. **必须基于用户提供的模板**复制 slide 并填充内容
2. **绝不从零创建** — 那会丢失模板的所有视觉设计（背景、装饰、配色、字体）
3. 模板中的每一页都是可复用的"版式画板"，按内容需要选择合适的源 slide 复制

**工作方式**：分析模板 → 理解每页的视觉用途 → 选择合适的源 slide → 复制并替换文本

## 适用范围

| 适用 ✅ | 不适用 ❌ |
|---------|-----------|
| 有 .pptx 模板 + 文档/文字内容 → 生成 PPT | 纯文字排版（用飞书/Word） |
| 基于已有模板填充新内容 | 修改已完成的 PPT 内容 |
| 把 PDF/文档转换为演示文稿 | 制作动画/视频 |

## 前置检测

```bash
# 检查 python-pptx
python3 -c "import pptx; print('python-pptx', pptx.__version__)" 2>/dev/null || \
  pip3 install python-pptx

# 检查 lxml (python-pptx 的依赖，通常自动安装)
python3 -c "import lxml" 2>/dev/null || pip3 install lxml
```

## 工具位置

```
~/.kiro/skills/pptx-gen/scripts/
├── analyze_template.py   # 分析模板结构
└── fill_template.py      # 复制模板 slide 并填充内容
```

---

## 核心流程

### Step 1: 分析模板

```bash
python3 ~/.kiro/skills/pptx-gen/scripts/analyze_template.py <template.pptx>
```

输出 JSON 包含每个 slide 的：
- `index` — slide 编号（duplicate_from 的值）
- `layout` — 版式名称
- `placeholders[]` — 标准占位符（idx, name, text）
- `textboxes[]` — 自由文本框（name, text, position）

**关键任务**：理解每个 slide 的视觉用途。例如：
- slide 0: 封面页（大标题 + 副标题）
- slide 3: 章节分隔页（深色背景 + 白色标题）
- slide 5: 内容页（标题 + 正文区域）
- slide 4: 图文混排页（左图 + 右侧标题和描述）

### Step 2: 规划内容映射

根据用户的内容源（文档/文字），将内容拆分为若干 slides，为每页选择最合适的模板源 slide：

| 内容类型 | 选择的模板 slide |
|---------|-----------------|
| 演示标题 | 封面页（通常 slide 0） |
| 议程/目录 | 带列表的内容页 |
| 章节分隔 | 深色分隔页（通常有特殊背景） |
| 要点列表 | 带正文的内容页 |
| 数据对比 | 图文页或内容页 |
| 总结/结束 | 封面页或分隔页 |

**规划原则**：
- 20 分钟演示 ≈ 12-18 页（每页 1-2 分钟）
- 每页一个核心观点，不堆砌信息
- 标题简洁（<15 字），正文要点化
- 变换版式避免视觉单调（不要连续用同一个源 slide）
- 长文本拆成多页，宁可多页也不要塞满一页

### Step 3: 生成 data.json

按照以下格式生成数据文件：

```json
{
  "slides": [
    {
      "duplicate_from": 0,
      "replacements": {
        "模板中的原标题文字": "新标题",
        "模板中的原副标题": "新副标题"
      }
    },
    {
      "duplicate_from": 5,
      "placeholders": {
        "0": {"type": "text", "content": "通过 placeholder idx 填充的标题"}
      },
      "replacements": {
        "其他文本框的原内容": "替换后的内容"
      }
    }
  ]
}
```

#### data.json 格式说明

每个 slide 必须有 `duplicate_from` 字段，指向模板中要复制的源 slide 索引。

**三种内容填充方式**（可组合）：

| 方式 | 用法 | 适用场景 |
|------|------|---------|
| `replacements` | `{"原文本": "新文本"}` | 最常用。通过模板中的现有文字定位文本框 |
| `textboxes` | `[{"match": "部分匹配文本", "content": "新内容"}]` | 同上，数组格式 |
| `placeholders` | `{"0": {"type": "text", "content": "..."}}` | 模板有标准 placeholder 时使用 |

**replacements 的 key 是模板中文本框的现有文字**（支持部分匹配）。通过 Step 1 分析结果中的 `textboxes[].text` 和 `placeholders[].text` 获取这些文字。

### Step 4: 填充生成

```bash
python3 ~/.kiro/skills/pptx-gen/scripts/fill_template.py \
  --template <模板.pptx> \
  --data <data.json> \
  --output <输出.pptx>
```

脚本会：
1. 打开模板
2. 按 data.json 顺序逐个复制指定的源 slide
3. 在复制的 slide 上替换文本内容（保留原有格式：字体、字号、颜色、对齐）
4. 移除模板中的原始 slide（只保留填充后的新 slide）
5. 保存为新 .pptx

### Step 5: 验证

```bash
# 提取生成的 PPT 文本内容进行检查
python3 -m markitdown <输出.pptx>
```

确认：
- 所有 slide 数量正确
- 标题和正文内容完整
- 没有遗留的模板占位文字（如 "Please Enter Your Headline"）

---

## 典型用法

### 从文档生成 PPT

```
用户：把这份 PDF 做成 PPT，用公司模板 template.pptx

Agent 执行：
1. 分析 template.pptx → 了解有哪些可用版式
2. 提取 PDF 内容 → 梳理关键信息
3. 规划内容映射 → 选择每页用哪个版式
4. 生成 data.json → 每页的 duplicate_from + replacements
5. 运行 fill_template.py → 生成 output.pptx
```

### 从文字大纲生成 PPT

```
用户：做个 PPT 介绍我们的新产品，模板在 brand_template.pptx

Agent 执行：
1. 分析模板
2. 根据用户描述组织内容
3. 直接生成 data.json（不需要额外的内容源）
4. 填充生成
```

---

## 已知限制

- **文本替换基于匹配**：如果模板中同一页有多个文本框文字完全相同，可能替换错误。此时用更具体的匹配文本
- **图片替换**：仅支持 placeholder 类型的图片占位符，自由放置的装饰图片会原样保留（这通常是期望的）
- **表格**：如果模板 slide 不含表格，不能凭空添加。建议在模板中预留带表格的版式
- **SmartArt / 3D / 动画**：不支持修改，但复制 slide 时会原样保留
- **字符溢出**：替换的文本比原文长很多时，可能超出文本框边界。规划内容时注意控制字数

## 备用方案（仅当无模板时）

极少数情况下用户确实没有模板，可使用 `create_deck.js` 从零创建：

```bash
node ~/.kiro/skills/pptx-gen/scripts/create_deck.js <config.json>
```

**但必须先询问用户是否有模板。** 大多数场景用户是有模板的。
