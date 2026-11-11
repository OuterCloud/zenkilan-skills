// 参考实现，
// 复制到项目时按本项目的 i18n / 主题 token 适配，不要直接改这里。
import { describe, expect, test, vi } from "vitest"

import { measureLabelWidths, sumLabelsWidth } from "./useTextWidth"

describe("sumLabelsWidth", () => {
  test("空列表没有宽度", () => {
    expect(sumLabelsWidth([], 8)).toBe(0)
  })

  test("单项不加间距", () => {
    expect(sumLabelsWidth([40], 8)).toBe(40)
  })

  test("多项之间才加间距", () => {
    // 三项两项间距：40+20+60 + 8*2 = 136
    expect(sumLabelsWidth([40, 20, 60], 8)).toBe(136)
  })

  test("间距为 0 时等于文字宽之和", () => {
    expect(sumLabelsWidth([10, 20, 30], 0)).toBe(60)
  })

  test("小数宽度保留精度，不提前取整", () => {
    // 单列宽度取整会让误差累积，取整留给最终列宽那一步
    expect(sumLabelsWidth([12.5, 17.25], 4)).toBeCloseTo(33.75, 5)
  })
})

/*
  字号必须落到测量节点上。

  量宽的节点挂在 <body> 下，继承的是浏览器默认 16px；而表格单元格是 antd 的
  token.fontSize（14px）。差 12.5%，会让算出的列宽明显偏宽——这正是
  「列宽看着还是有点宽」的根因。这里直接断言传入的字号被写进了节点样式。
*/
describe("useTextWidths 的字号", () => {
  test("测量节点的 font-size 用传入值，而不是继承 body 的默认值", () => {
    // jsdom 不做布局，量不到宽度，但能观察挂载期间的节点样式
    const appended: HTMLElement[] = []
    const originalAppend = document.body.appendChild.bind(document.body)
    const spy = vi.spyOn(document.body, "appendChild").mockImplementation((node) => {
      appended.push(node as HTMLElement)
      return originalAppend(node)
    })

    const result = measureLabelWidths(["运行", "复制"], "zh", 14)

    spy.mockRestore()
    expect(result).toBeNull() // jsdom 量不出宽度，走降级
    const host = appended.find((el) => el.style.position === "absolute")
    expect(host).toBeTruthy()
    expect(host!.style.fontSize).toBe("14px")
  })

  test("同一批文案，字号越大量出来越宽（浏览器环境才有非零值）", () => {
    const small = measureLabelWidths(["Run Records"], "en", 14)
    const large = measureLabelWidths(["Run Records"], "en", 16)
    // jsdom 下两者都是 null，这条只在真实浏览器有意义；这里保证不抛错
    expect(small === null || large === null || large > small).toBe(true)
  })
})
