---
name: antd-column-width
version: 1.0.0
description: "修 antd Table 列宽问题，尤其是 fixed 列（操作列）宽度写死导致中文留白过多、切英文折行的情况：按当前语言运行时实测文案宽度算出列宽，并顺带修正 scroll.x 推导、名称列吸收富余。当用户说「操作列太宽/太窄」「切英文就折行」「列宽不要写死」「自适应列宽」时使用。不负责：非 antd 的表格、需要按内容自动换行的多行单元格、纯 CSS 层面的栅格布局。"
metadata:
  requires:
    bins: [node]
---

# antd 列宽自适应

一句话：**antd 的 fixed 列宽度必须是具体 px，所以「不写死」只能落成「按当前语言实测后算出来」。**

## 先判断：需不需要动用测量方案

按顺序问，命中就停，不要过度工程：

| 情况 | 做法 |
|------|------|
| 目标表**没有** fixed 列 | 别测量。用 `minWidth`，或不设 width 让某一列吸收富余 |
| 有 fixed 列，但文案**不随语言变**（纯数字、纯 ID） | 直接给常量，加注释说明为什么是这个值 |
| 有 fixed 列，文案随语言变（操作列、状态列） | 走本文的实测方案 |
| fixed 列 + 单元格内容会**换行**（长描述） | 不适合本方案：本方案算的是「一行展示」需要多宽 |

## 为什么不能靠 antd 自己收缩（已实测，别重试）

这些路都在真实环境验证过，全部失败：

| 方案 | 结果 |
|------|------|
| `scroll.x: "max-content"` | 带 fixed 列时 rc-table 强制 `table-layout: fixed`，实测被等分成 400px |
| `minWidth`（rc-table 1.9 已有该字段） | 只有 `table-layout: auto` 时才写进 `<col>`，固定列场景完全失效 |
| `width: "1%"` 收缩技巧 | fixed 布局下被压成 10px |
| `maxWidth` | 同上，不写进 `<col>` |

根因：fixed 列靠 sticky 吸附，吸附偏移按列宽数值累加，所以必须能算出确定像素。ant-design#46824 至今 open。

## 实现五步

### 1. 量文案宽度（复用 `references/useTextWidth.ts`）

把 `references/useTextWidth.ts` 放进项目的 `src/hooks/useTextWidth.ts`（已存在就复用，别新造一份）。
它做下面这几件事，逐条都要有，少一条就会在某个场景悄悄量错：

- 往 `<body>` 挂离屏 `span`（`position:absolute; left:-9999px; visibility:hidden; white-space:pre`），用 `getBoundingClientRect()` 量；
- 设 `host.lang = i18n.language`（中日韩按语言选字形，不设会偏）；
- **显式设 `font-size`**，见下面第 3 步的坑；
- `document.fonts.ready` 之后再量一次（自定义字体晚到会让首屏测值偏窄）；
- 全 0 视为「量不到」返回 `null`（jsdom 无布局），交给调用方兜底；
- **effect 依赖必须是文案内容，不能是 `items` 数组引用**，见第 4 步。

> 这份参考实现曾经就是错的：`useEffect` 依赖写成 `[items, ...]`，而调用方传的是内联数组字面量，
> 于是每次渲染都重新量宽 + `setState`，浏览器实测每秒上百次重渲染，把 React 的 transition 拖死——
> 页面点任何按钮 URL 变了但画面不动，而且控制台一条报错都没有。参考文件已修，别再改回去。

不用 canvas：canvas 要显式指定字体，等于把 antd 字体栈抄一份进代码，主题一改就悄悄失准，而且 jsdom 没有 canvas 会刷噪声。

### 2. 列宽公式

```
列宽 = 各动作文案宽之和 + 项间距 × (n-1) + 图标一个字号(1em) + 项间距 + token.padding × 2
```

- 文案从 `t(...)` 取，**必须和 render 里用的是同一批 key**，否则算的和渲染的对不上；
- 末项如果是纯图标（如 `EllipsisOutlined`），宽度按 `token.fontSize` 算（1em），不要再估一个数；
- 单元格左右内边距用 `token.padding * 2`，不要手写 16。

### 3. 最大的坑：字号必须显式传

测量 span 挂在 `body` 下，继承的是浏览器默认 **16px**，而 antd 表格单元格是 `token.fontSize`（**14px**），差 12.5%。

照着 16px 量出来的列宽会明显偏宽——这就是「改完看着还是有点宽」的真正原因，不是公式错了。

所以 `useTextWidths(items, fontSizePx)` 必须接收 `token.fontSize`，并写进测量节点的 `font-size`。
**排查列宽偏宽时，先量一下测量节点的 computed font-size，再怀疑公式。**

### 4. 把「重渲染自激」堵死（最容易埋雷的一步）

调用方几乎一定写成内联数组：

```tsx
const actionLabels = [t("run"), t("manage.copy"), t("manage.viewRecords")]
const widths = useTextWidths(actionLabels, token.fontSize)   // 每次渲染都是新数组
```

如果 hook 里依赖直接写 `[items, i18n.language, fontSizePx]`，就会形成闭环：

```
渲染 -> effect 重跑 -> 量宽（往 body 挂 span）-> setWidths -> 渲染 -> effect 又重跑 ...
```

实测后果：每秒上百次提交，React 的 transition 永远提交不掉。**表现极具欺骗性**——
点按钮 URL 变了、画面不动、没有 loading、控制台零报错、主线程也不卡（JS 照样能执行），
很容易被误判成路由或 i18n 的 Suspense 问题。真实事故就是按这个方向误诊了一轮。

正确写法（两个措施都要）：

```ts
// 1) 依赖用文案内容，文案真的变了（如切语言）才重量
const itemsKey = items.join("\u0000")
const itemsRef = useRef(items)
itemsRef.current = items

// 2) 量到的宽度和上次一样时不要 setState，切断无意义重渲染
setWidths((prev) => (sameWidths(prev, next) ? prev : next))
```

`items` 用 `\u0000` 拼接做 key：文案里不会出现这个字符，不会拼出歧义。

**验收必须包含一条「多次渲染只量一次宽」的回归用例**（见 `references/useTextWidth.test.ts`）：
用 `renderHook` 传内联数组，`rerender()` 若干次，断言测量节点挂载次数不变。
把 hook 改回 `[items]` 这条用例要能失败——不能失败的用例等于没有。

### 5. 间距常量必须和 `<Space size>` 共用

```ts
const ACTION_ITEM_GAP = 8   // 与下面 <Space size={ACTION_ITEM_GAP}> 同一个值
```

两处不一致的后果：宽了右留白、窄了折行。抽成常量给两边共用，禁止在 render 里写别的字面量。

### 6. 让某一列吸收富余，并推导 scroll.x

```tsx
// 名称列刻意不设 width：整张表必须留一列承接富余
const scrollX = Math.ceil(FIXED_COL_WIDTH_TOTAL + ACTION_COL_WIDTH + NAME_COL_MIN_WIDTH)
```

- 如果每列都钉死宽度，富余会**按比例摊给每一列**，操作列被撑到 300 多 px，右侧空一大片；
- `scroll.x` 必须由各列宽推导，不要单独留魔数：给小了自由列被压到 0 再靠横滚兜底，给大了多出来的部分全落到那唯一没有宽度的列上；
- 吸收富余的那一列要选**最需要空间**的内容列（名称/标题），不要选操作列。

## 兜底策略

```ts
const ACTION_COL_WIDTH_FALLBACK = 240  // 取英文实测值向上留余量
```

量不到时（jsdom、样式未加载）回落到常量。**宁可略宽，不能略窄**：宽了只是多留白，窄了会把按钮挤到折行，那是真问题。兜底值按最长的语言（一般是英文）定。

## 验证清单

改完必须给出证据，不要只说「应该没问题了」：

1. `tsc --noEmit`、`eslint --max-warnings=0` 通过；
2. 单测至少两条：
   - 断言测量节点的 `font-size` 是传入值、不是继承的 16px（防回归到第 3 步的坑）；
   - 断言同一批文案在英文下比中文宽；
3. 真实浏览器里量出中英文的**实际列宽像素**，列成改动前 / 改动后对比表；
4. 切英文确认最长文案不折行（截图为证）；
5. 窗口拉宽/拉窄，确认富余落在预期的那一列，操作列宽度不变；
6. 页面挂上后静置观察：React root 不应持续重渲染。在控制台跑下面这段，`flips` 应该是个位数：

```js
const r = document.querySelector('#root')
const k = Object.keys(r).find((x) => x.startsWith('__reactContainer'))
const root = r[k].stateNode
let flips = 0, last = root.current
const iv = setInterval(() => { if (root.current !== last) { flips++; last = root.current } }, 0)
setTimeout(() => { clearInterval(iv); console.log('flips', flips) }, 2000)
```

无头 Chrome 量 DOM 的写法（拿不到 DevTools 时用）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --dump-dom --virtual-time-budget=5000 <url> > /tmp/dom.html
```

## 常见误判

| 现象 | 常见真因 |
|------|---------|
| 改完还是偏宽 | 字号继承了 16px（见第 3 步） |
| 切英文折行 | 兜底值按中文定的；或列的 `white-space` 没设 `nowrap` |
| 窗口变宽操作列跟着变宽 | 有其他列没设 width，富余被按比例摊开 |
| 首屏窄、刷新后变宽 | 测完字体就绪又量了一次，属预期；若稳定偏窄说明没在 `fonts.ready` 后重量 |
| 测试里列宽一直是兜底值 | jsdom 不做布局，属预期，不要为此改断言 |
| **点任意按钮 URL 变了、画面不动、控制台零报错** | 量宽 hook 的 effect 依赖写了 `items` 数组，调用方传内联字面量 -> 无限重渲染把 transition 拖死（见第 4 步）。排查：在控制台量 2 秒内 React root 的 `current` 翻转次数，正常是几次，中毒是上百次 |

## 适用范围

适用于 antd v5 + rc-table（`table-layout: fixed` + sticky fixed 列）。其他表格库要看它是否也用 sticky 累加偏移，原理相同但 API 不同。
