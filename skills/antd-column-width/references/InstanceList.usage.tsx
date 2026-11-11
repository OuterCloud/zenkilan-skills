// 参考用法，提炼自一个真实项目的实例列表页。
// 只截取与列宽相关的部分，import 与业务逻辑按项目自行适配。

/* ---------- 模块级常量 ---------- */

/** 操作列里逐个动作之间的间距（与 render 里 <Space size> 共用同一个值） */
const ACTION_ITEM_GAP = 8

/** 量不到文案宽度时的兜底列宽：取最长语言（英文）实测值再留一点余量 */
const ACTION_COL_WIDTH_FALLBACK = 240

/*
  除内容主列以外的固定宽度列。主列刻意不给宽度，由它吸收富余。
  scroll.x 必须不小于这些列之和，否则自由列会被压到 0 再靠横滚兜底。
*/
const FIXED_COL_WIDTHS = {
  id: 100,
  triggerType: 160,
  operateUser: 120,
  creator: 160,
  operateTime: 180,
} as const

const FIXED_COL_WIDTH_TOTAL = Object.values(FIXED_COL_WIDTHS).reduce(
  (sum, w) => sum + w,
  0
)

/** 主列的最小宽度；再窄就只剩几个字，标题也失去意义 */
const NAME_COL_MIN_WIDTH = 250

/* ---------- 组件内 ---------- */

  const { token } = theme.useToken()

  /*
    文案必须和下面 render 里 t(...) 用的是同一批 key。
    末项「更多」是图标不是文字，宽度按一个字号算，所以不放进这个数组。

    这里允许写成内联数组（每次渲染都是新引用）：useTextWidths 内部按文案内容做依赖，
    不会因为引用变化重新量宽。前提是那份 hook 用的是修复后的版本（见 references/useTextWidth.ts）。
    如果换成自己重写、依赖直接写 [items]，就会每次渲染都量一遍并 setState，
    形成每秒上百次的重渲染，页面点哪都不跳（详见 SKILL.md「常见误判」）。
  */
  const actionLabels = [
    t("run", "运行"),
    t("manage.copy", "复制"),
    t("manage.viewRecords", "运行记录"),
  ]

  // 关键：第二个参数传单元格字号。不传或传错（如照 body 的 16px 量）会偏宽 12.5%。
  const actionLabelWidths = useTextWidths(actionLabels, token.fontSize)

  const ACTION_COL_WIDTH =
    actionLabelWidths === null
      ? ACTION_COL_WIDTH_FALLBACK
      : Math.ceil(
          sumLabelsWidth(actionLabelWidths, ACTION_ITEM_GAP) +
            // 图标字形宽度就是一个字号（1em），再加上它与前一项的间距
            token.fontSize +
            ACTION_ITEM_GAP +
            // 单元格左右内边距
            token.padding * 2
        )

  // scroll.x 由各列宽度推导，不要再单独写一个魔数
  const scrollX = Math.ceil(
    FIXED_COL_WIDTH_TOTAL + ACTION_COL_WIDTH + NAME_COL_MIN_WIDTH
  )

/* ---------- 列定义 ---------- */

  const columns: ColumnsType<WorkflowListItem> = [
    {
      title: t("workflowName"),
      dataIndex: "name",
      key: "name",
      fixed: "left",
      // 刻意不设 width：整张表留这一列承接富余，
      // 否则富余会被按比例摊给每一列，操作列被撑宽、右侧空一大片。
    },
    // ... 其余定宽列，宽度取 FIXED_COL_WIDTHS ...
    {
      title: t("operate"),
      key: "action",
      fixed: "right",
      width: ACTION_COL_WIDTH,
      render: (_, record) => (
        // white-space 可继承，加在 Space 上即可让链接都不折行；
        // 间距必须与 ACTION_ITEM_GAP 一致，否则算出的宽度和真实排版对不上
        <Space size={ACTION_ITEM_GAP} className="whitespace-nowrap">
          {/* ... 动作 ... */}
        </Space>
      ),
    },
  ]

/* ---------- Table ---------- */

  <Table
    columns={columns}
    scroll={{ x: scrollX, y: "calc(100vh - 340px)" }}
  />
