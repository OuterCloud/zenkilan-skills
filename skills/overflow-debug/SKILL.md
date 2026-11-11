---
name: overflow-debug
version: 1.0.0
description: "排查「内容显示不全 / 滚不动 / 窄屏被裁 / 表格右侧看不到」这类横向溢出问题：先用脚本量真实 DOM 找出是谁在裁切，再改代码。当用户说「显示不全」「不能左右滚」「小窗口看不到」「列挤在一起」「被裁掉了」时使用。不负责：垂直方向的高度/滚动问题、非布局类的样式错位（间距、颜色、字号）、移动端手势与惯性滚动。"
metadata:
  requires:
    bins: [node, chrome]
---

# overflow-debug —— 先量，再改

一句话：**用户说「显示不全 / 滚不动」时，先别急着给内层容器加 `overflow-x: auto`——更常见的是外层某个祖先写了 `overflow: hidden` + 固定 `min-width`，把整个滚动容器裁到视口外了。改代码之前先量。**

## 铁律

1. **没跑过一次 probe，不许改 CSS。** 每次「我觉得是列宽 / 是 flex / 是滚动容器」的猜测，实测都会被证伪。
2. **改完必须用同一个视口再跑一次**，`clippedCount` 必须为 0，且那个本该滚的容器要被报成 `→ 可滚动`（`overflowBy > 0`）。
3. 结论里必须写出**被裁的元素 + 它的 `overflow-x` + `min-width`**，不能只说「已修好」。

## 第一步：跑 probe

```bash
node scripts/overflow-probe.mjs <url> --viewport 700x900
```

窄屏问题**必须显式传窄视口**（如 `--viewport 700x900`），默认 1440 宽根本触发不了问题。

常用参数：

| 参数 | 用途 |
|------|------|
| `--viewport WxH` | 视口尺寸，窄屏必传 |
| `--from <selector>` | 只量某个区域，减少噪声。脚本会自动额外扫它的祖先链——裁切点经常在该区域**外面** |
| `--json <path>` | 完整结果落盘，便于改动前后 diff |
| `--screenshot <path>` | 截图，配合 JSON 一起交付 |
| `--wait-ms <ms>` | 导航后静置，等 SPA 渲染完（默认 3000） |
| `--cookie k=v` | 需要登录态时带上 |
| `--strict` | 有 clipped 就退出码 1，可接 CI 门禁 |

脚本自带独立无头 Chrome，不碰你正在用的浏览器实例，也不用装 Playwright。

## 三类溢出：先分清是哪种，再决定改哪

| 分类 | 判据 | 含义 | 处理 |
|------|------|------|------|
| `scrollable` | `scrollWidth > clientWidth` 且 `overflow-x: auto/scroll` | 内容超出但**能滚**，只是用户没发现 | 通常没问题；需要时加视觉提示（滚动条常显、右侧渐隐） |
| `clipped` | `scrollWidth > clientWidth` 且 `overflow-x: hidden/clip` | 内容**看不见也滚不到**，这就是用户说的「显示不全」 | 找裁切点，改掉写死的 `min-width` 或 `overflow: hidden` |
| `visible` | `overflow-x: visible` | 溢出交给上层，自己既不是滚动容器也不是裁切点 | 跳过，继续往上找 |

**只有 `clipped` 才是 bug。** 见到 `scrollable` 就去加 `overflow-x-auto` 是无效劳动；见到 `visible` 就该往上追。

## 输出怎么读

```
❌ 被裁  溢出 200px  div.shell
        client=700 scroll=900 w=700 overflow-x=hidden min-width=0px display=flex
        祖先链（找第一个 overflow-x: hidden 的就是裁切点）:
          body  w=700 client=700 scroll=700 overflow-x=visible min-width=0px
```

- `溢出 200px`：内容比可见区多 200px，这 200px 用户永远看不到。
- 看 `某元素 client=700 scroll=900`：`scrollWidth` 记的是**内容**宽度，`clientWidth` 是可见宽度。
- 祖先链从上往下看，**第一个 `overflow-x: hidden` 且 `scrollWidth > clientWidth` 的就是裁切点**。
- 若被裁元素自己就是 `min-width: 900px`，那 `min-width` 那行会直接指认元凶。

## 改哪里

按命中顺序排查，命中就停：

| 检查项 | 典型写法 | 改法 |
|--------|----------|------|
| 硬编码最小宽度 | `min-w-225`（=900px）、`min-width: 900px`、`minWidth: 1200` | 改成 `min-w-0` / `min-width: 0`，把「最小多宽」交给真正需要的那个内层容器 |
| 外壳裁切 | `overflow: hidden` + 上面那条 min-width | 宽度下限去掉后，外壳的 `overflow-hidden` 通常可以保留（防止整页横向抖动），滚动交给内层 |
| flex 子项不肯缩 | `flex: 1` 的子项里放 `min-w-*` | 见 `references/flex-grid-minwidth.md` |
| grid/表格内部 | 列宽写死、`grid-template-columns` 用 px 且总和超视口 | 给**滚动容器**一个 `min-width`，让它成为唯一可滚的东西 |

**一条原则：整个页面只允许有一个「宽度下限」和一个「滚动容器」。** 外壳设了 900px 下限又设 hidden，内层再怎么 `overflow-x-auto` 都滚不动——因为滚动容器本身已经被裁到视口外，物理上不存在。

## 验收（必须做，不能靠肉眼）

```bash
# 改前
node scripts/overflow-probe.mjs <url> --viewport 700x900 --json /tmp/before.json
# 改后
node scripts/overflow-probe.mjs <url> --viewport 700x900 --json /tmp/after.json
```

通过标准，三条全中才算修好：

1. `after.clippedCount === 0`；
2. 本该横向滚动的那个容器，在 `after.findings` 里是 `scrollable`，且 `overflowBy > 0`（说明确实还留着可滚内容）；
3. `doc.scrollWidth === doc.clientWidth`（整页不再横向溢出，避免把问题从「裁切」变成「整页横滚」）。

再补一个大视口（1440）确认没把正常布局改坏。

## 常见误判

| 现象 | 常见误判 | 真实原因 |
|------|----------|----------|
| 表格右侧被切 | 列宽不够 / 间距太小 | 外壳 `min-width` + `overflow: hidden` 把整个内容裁到视口外 |
| 小窗口不能左右滚 | 缺 `overflow-x-auto` | 滚动容器自身被祖先裁掉了，overflow 设置无效 |
| 加了 `overflow-x-auto` 还是不行 | 父级 `min-width: auto` 撑着 | flex/grid 子项的默认 `min-width: auto` 不让它缩到内容宽度以下 |
| 表格能滚，但分组行右侧留白 | 分组行没参与滚动 | 分组行在 grid 外，没继承表格的 `minWidth`，需共用同一个宽度常量 |
| 给行加 `sticky left-0` 后表头文字消失 | — | sticky 让整行脱离滚动流，别再叠加 sticky，只对齐宽度 |

## 本次真实教训（后端管理台的批量发布页）

用户反馈「应用列被挤窄」，连续四轮都靠猜改 CSS：先加列间距，再调表单宽度，再加 `overflow-x-auto`，再改 flex 居中——**全部无效**。第五轮才去量 DOM，量出外壳 `min-w-225`（900px 硬下限）+ `overflow: hidden`，视口 700px 时整个内容被裁在视口外，而表格自己其实能滚 176px。

完整复盘（含实测数字、每个错误猜测的证伪过程）见 `references/case-narrow-clipped-shell.md`。

起因是「四次猜测」而不是「一次测量」，代价是四个 commit 全部白改。**这就是本 skill 存在的理由。**

## 适用范围

- 适用：桌面 Web、Electron、SPA 管理后台的横向溢出/裁切问题。
- 不适用：垂直滚动、移动端手势、canvas 内部缩放、`transform: scale` 造成的视觉溢出（probe 只看布局宽度，不看变换）。

## 自检

改动 probe 之后跑一次回归（需要本机 Chrome，或 `CHROME_PATH` 指向可执行文件）：

```bash
bash tests/run.sh
```

两个 fixture 分别代表「外壳写死 900px 被裁」和「外壳放开、表格自己可滚」，断言 probe 能正确区分这两类。
