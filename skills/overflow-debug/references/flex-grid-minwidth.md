# flex / grid 子项的 `min-width: auto`

横向布局里「怎么都缩不下去」「内层设了 overflow 还是不滚」，八成是因为这条：

```css
/* 规范默认值 */  .item { min-width: auto }
```

`min-width: auto` 的语义是 **「不小于内容的最小尺寸」**。对 flex 子项和 grid 子项都成立，
但两者的「内容最小尺寸」算法不一样，踩坑表现也不同。

## 表现一：flex 子项撑破父级

```html
<div style="display:flex; width:700px">
  <div style="flex:1">            <!-- 没有 min-width:0 -->
    <div style="width:1200px">很宽的表格</div>
  </div>
</div>
```

期望：`flex:1` 的子项被压到 700px，里面的表格自己横向滚。
实际：子项被内容撑到 1200px，父级 `overflow:hidden` 直接裁掉右边 500px。

原因：`flex:1` 展开是 `flex-grow:1; flex-shrink:1; flex-basis:0%`，
**收缩下限仍受 `min-width: auto` 约束**，内容多宽它就多宽，`flex-shrink` 无能为力。

修法：给需要收缩的子项显式 `min-width: 0`（在 Tailwind 里就是 `min-w-0`）。

```html
<div style="display:flex; width:700px">
  <div style="flex:1; min-width:0">
    <div style="overflow-x:auto"> <div style="width:1200px">…</div> </div>
  </div>
</div>
```

**注意 `min-width: 0` 要加在「需要变窄的那一层」**，加在再上一层的父级无效——
每层 flex 容器都得把这个约束往下传。

## 表现二：grid 子项里 `truncate` 失效

```html
<div style="display:grid; grid-template-columns: 200px 1fr">
  <div class="truncate">这一串很长的文字……</div>
</div>
```

`truncate` = `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`。
三个属性都在，但就是不出现省略号，而是把整行撑宽。

原因同上：grid 子项的 `min-width: auto` 让它不小于文字长度，
`1fr` 轨道因此被撑开，`overflow:hidden` 没有可裁的余量。

修法：同样 `min-width: 0`（grid 下也可用 `minmax(0, 1fr)` 直接写死轨道）。

```css
grid-template-columns: 200px minmax(0, 1fr);
```

`minmax(0, 1fr)` 比给每个子项加 `min-width:0` 更稳，因为它在轨道层面就压掉了 auto 下限。

## 表现三：`overflow` 写了但不生效

```html
<div style="min-width:900px; overflow:hidden">      <!-- 外壳 -->
  <div style="overflow-x:auto">                      <!-- 想让它滚 -->
    <table style="min-width:700px">…</table>
  </div>
</div>
```

视口 700px 时用户看不到右侧内容。**这不是「overflow 写错了」，是外壳压根不该有 900px 下限。**
滚动容器被裁到视口外，物理上不存在，里面的 `overflow-x:auto` 再正确也没用。

判别方法：量 `document.documentElement.scrollWidth`。
如果它等于 `clientWidth`（没有整页横滚），但用户明显看不全，那就是**有东西被 hidden 裁掉了**，
不是滚动区不够宽。用 `scripts/overflow-probe.mjs` 一把就能定位。

## 速查

| 症状 | 先查 |
|------|------|
| flex 子项压不下去 | 该子项有没有 `min-width: 0` |
| grid 里 `truncate` 不生效 | 轨道写没写 `minmax(0, 1fr)` |
| 内层 `overflow-x:auto` 不滚 | 祖先有没有 `min-width: <大数>` + `overflow: hidden` |
| 整页能横滚但不该横滚 | 某个元素的下限超出了视口，把它改成 0，让内层接管滚动 |
| 只有窄屏出问题 | 大概率是某个 pb 级别的 `min-w-225` 之类的硬编码下限 |

## 一条经验

`min-width` 写具体像素值时，问自己一句：**「窗口比这个值小时，用户应该看到什么？」**
如果答案是「看到滚动条」，那这个 `min-width` 必须落在**滚动容器自己**身上，
而不是它的祖先；如果答案是「布局重新排」，那就不该有 `min-width`，该用响应式断点。
