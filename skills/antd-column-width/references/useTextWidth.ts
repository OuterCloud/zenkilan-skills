// 参考实现，
// 复制到项目时按本项目的 i18n / 主题 token 适配，不要直接改这里。
// 注意：这一份已经包含「依赖必须用文案内容、不能用 items 数组引用」的修复，详见 useTextWidths 上方注释。
import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

/** 两次量宽结果是否等价：都为 null，或每个元素都相同。 */
function sameWidths(
  prev: number[] | null,
  next: number[] | null
): boolean {
  if (prev === next) return true
  if (prev === null || next === null) return false
  if (prev.length !== next.length) return false
  return prev.every((w, i) => w === next[i])
}

/**
 * 量出一组文案在「当前语言」下各自的像素宽度。
 *
 * 为什么需要它：antd Table 的固定列（fixed: left / right）靠 sticky 吸附实现，
 * 吸附偏移按列宽累加，所以宽度必须是具体像素值。antd 的 minWidth 只在
 * table-layout: auto 时才会写进 <col>，而带固定列的表会被 rc-table 强制成
 * table-layout: fixed（见 @rc-component/table/es/Table.js 的 mergedTableLayout），
 * 于是「不写死宽度」只能落成「按当前语言实测后算出来」。
 *
 * 文案长度随语言变化，写死一个值要么中文留白过多、要么英文挤到折行。
 * 按语言量一次，两种语言都刚好。
 *
 * 字号必须显式传入（单元格的 cellFontSize 取 antd 的 token.fontSize）。
 * 不能靠继承：量宽用的 span 挂在 <body> 上，而 body 继承的是浏览器默认 16px，
 * 比单元格的 14px 大 12.5%，照着 16px 量出来的宽度会明显偏宽——正是
 * 「列宽看着还是有点宽」的来源。
 *
 * 量不出来时返回 null（jsdom 不做布局，量到的宽度恒为 0；样式也可能尚未加载），
 * 调用方据此回落到保守常量——宁可略宽，也不要窄到把按钮挤折行。
 */
export function useTextWidths(
  items: readonly string[],
  fontSizePx: number
): number[] | null {
  const { i18n } = useTranslation()
  const [widths, setWidths] = useState<number[] | null>(null)

  /*
    依赖里不能直接用 items 数组本身。

    调用方通常写成内联数组字面量（例如 [t("run"), t("copy")]），每次渲染都是新引用，
    effect 会跟着重跑：量宽 -> setWidths -> 重渲染 -> 再量宽。量宽是真的往 body 挂节点，
    这个自激循环能把主线程占满，React 的 transition 永远提交不了，表现为 URL 变了
    但页面不更新、控制台却没有任何报错（缺陷 7165050794 的连带问题）。

    所以用文案内容做依赖：只有文案真的变了（例如切语言）才重新量。
    数组用 \u0000 拼接，文案里不会出现这个字符，不会拼出歧义。
  */
  const itemsKey = items.join("\u0000")
  const itemsRef = useRef(items)
  itemsRef.current = items

  useEffect(() => {
    let cancelled = false
    const measure = () => {
      if (cancelled) return
      const next = measureLabelWidths(itemsRef.current, i18n.language, fontSizePx)
      // 量到的宽度一模一样时不再 setState，避免无意义的重渲染。
      setWidths((prev) => (sameWidths(prev, next) ? prev : next))
    }

    measure()

    /*
      字体晚于首屏加载时（自定义字体、字体回退切换），同一段文字的实际宽度会变，
      首屏量到的值就不准了。fonts.ready 在所有字体就绪后 resolve，再量一次即可。
      jsdom 没有 document.fonts，直接跳过。
    */
    const fonts = document.fonts
    if (fonts?.ready) {
      fonts.ready.then(measure).catch(() => {})
    }

    return () => {
      cancelled = true
    }
    // items 由调用方按当前语言翻译得到；语言变化时内容会变，
    // 这里同时显式带上 language 作为触发条件，避免调用方传入稳定数组时漏掉重算。
  }, [itemsKey, i18n.language, fontSizePx])

  return widths
}

/**
 * 用一段离屏 DOM 量文案宽度。
 *
 * 不用 canvas：canvas 必须显式指定字体，等于把 antd 的字体栈抄一份到代码里，
 * 主题一改（换字号、换字体族）这里就悄悄失准，而且 jsdom 没有 canvas 实现，
 * 测试里会往控制台刷 "Not implemented" 噪声。
 *
 * 挂一个 span 进 body 量，字体直接继承页面真实样式，量到多少就是渲染出来多少；
 * 量完立刻移除，不留在 DOM 里（只在挂载、切语言、字体就绪时各跑一次）。
 */
export function measureLabelWidths(
  items: readonly string[],
  language: string | undefined,
  fontSizePx: number
): number[] | null {
  if (typeof document === "undefined") return null
  if (items.length === 0) return null
  if (!document.body) return null

  const host = document.createElement("span")
  // 离屏且不参与布局：position:absolute 让它脱离文档流，visibility:hidden 保证不可见
  // 字号显式写成单元格的实际字号：继承 body 会拿到浏览器默认的 16px，量偏大
  host.style.cssText = `position:absolute;top:0;left:-9999px;visibility:hidden;white-space:pre;pointer-events:none;font-size:${fontSizePx}px`
  // 带上 lang：中日韩字形按语言选字体（如 ja 与 zh 共用汉字但字形不同），
  // 不加这行，同一段汉字在不同语言下量的宽度会和真实渲染有偏差。
  if (language) host.lang = language

  const spans = items.map((item) => {
    const el = document.createElement("span")
    el.textContent = item
    host.appendChild(el)
    return el
  })

  document.body.appendChild(host)
  try {
    const measured = spans.map((el) => el.getBoundingClientRect().width)
    /*
      jsdom 不实现布局，getBoundingClientRect 恒返回 0；样式还没加载时也可能量到 0。
      全 0 视为「量不到」而不是「文案宽度为 0」，否则会算出一个 0 宽的固定列。
    */
    if (!measured.some((w) => w > 0)) return null
    return measured.every((w) => Number.isFinite(w) && w >= 0) ? measured : null
  } finally {
    host.remove()
  }
}

/**
 * 按文案宽度算出「并排展示」需要的总宽：文字宽 + 项间距。
 *
 * 单独导出而不是塞进 hook，是因为它是纯计算，可以直接写测试覆盖边界
 * （空列表、单项、小数），不必去渲染一个表格。
 */
export function sumLabelsWidth(widths: readonly number[], gapPx: number): number {
  if (widths.length === 0) return 0
  return widths.reduce((sum, w) => sum + w, 0) + gapPx * (widths.length - 1)
}
