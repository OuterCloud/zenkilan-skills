# zenkilan-skills

个人沉淀的 Kiro CLI 自定义 Skills 合集。

## Skills

| Skill | 说明 |
|-------|------|
| [web-probe](./web-probe/) | 前端自动化验证：用本机 Chrome 打开指定 URL，按需截图、抓网络请求（HAR/JSON）、收集 console 日志 |
| [feishu-doc-collab](./feishu-doc-collab/) | 飞书文档协作：通过飞书云文档与团队成员进行异步协作（环境检测、配置引导、文档读写、评论、搜索） |

## 使用方式

将对应 skill 目录复制或软链到 `~/.kiro/skills/` 下即可在 Kiro CLI 中使用：

```bash
# 示例：链接 web-probe
ln -s $(pwd)/web-probe ~/.kiro/skills/web-probe

# 示例：链接 feishu-doc-collab
ln -s $(pwd)/feishu-doc-collab ~/.kiro/skills/feishu-doc-collab
```
