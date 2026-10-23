# 示例

`mr-128.json` 是一份**完全虚构**的完整走读内容（`acme/order-service` 的领券幂等修复），
用来演示 `content.json` 的每个字段可以写到什么颗粒度。`mr-128.html` 是它渲染后的样子，双击即可看效果。

- 起步方式：复制 `mr-128.json` 改字段，字段定义见 [../references/content-schema.md](../references/content-schema.md)。
- 内容与任何真实公司、项目、人员无关：域名只有 `gitlab.example.com`，业务数据、代码、事故编号都是编的。
- 示例故意覆盖了这些容易漏的部分：带 DDL 的数据库改造、冲突回读这类"为什么不能换写法"的步骤、
  以及 `open_questions` 里真实未决的问题。
