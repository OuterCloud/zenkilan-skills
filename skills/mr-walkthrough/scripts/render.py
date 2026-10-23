#!/usr/bin/env python3
"""Validate a walkthrough content JSON and render it into a single offline HTML file.

Usage:
    render.py content.json --out mr-233.html [--open] [--check]

The content model is documented in references/content-schema.md. Validation is
intentionally strict: a broken walkthrough is worse than no walkthrough, so we
fail with a precise path (steps[2].title) instead of shipping a half-rendered page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
PLACEHOLDER = "<!--MR_DATA-->"

ROLES = {"core", "test", "config", "migration", "doc", "generated", "context"}
CHANGES = {"added", "modified", "deleted", "renamed", "context"}
LEVELS = {"high", "medium", "low"}
STATUSES = {"fixed", "changed", "unchanged"}
TEST_TYPES = {"unit", "integration", "e2e", "manual"}
TODO_RE = re.compile(r"\bTODO\b|待填|XXX", re.I)


class ValidationError(ValueError):
    pass


def fail(path: str, msg: str) -> None:
    raise ValidationError(f"{path}: {msg}")


def need(obj: dict, key: str, path: str, typ=None, nonempty: bool = False):
    if key not in obj:
        fail(f"{path}.{key}", "缺少字段")
    val = obj[key]
    if typ and not isinstance(val, typ):
        fail(f"{path}.{key}", f"类型应为 {typ.__name__}，实际 {type(val).__name__}")
    if nonempty and (val is None or (isinstance(val, (str, list, dict)) and len(val) == 0)):
        fail(f"{path}.{key}", "不能为空")
    return val


def check_text(value, path: str, nonempty: bool = True) -> None:
    if not isinstance(value, str):
        fail(path, "应为字符串")
    if nonempty and not value.strip():
        fail(path, "不能为空")
    if TODO_RE.search(value):
        fail(path, f"仍含占位符: {TODO_RE.search(value).group(0)!r}")


def validate(data: dict) -> list[str]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        fail("root", "顶层应为对象")
    if data.get("schema_version") != 1:
        fail("schema_version", "必须为 1")

    meta = need(data, "meta", "root", dict)
    for key in ("title", "project", "author", "source_branch", "target_branch", "state"):
        check_text(need(meta, key, "meta", str), f"meta.{key}")
    # Local and generic-diff walkthroughs have no web URL; the page hides the button then.
    if not isinstance(meta.get("mr_url"), str):
        fail("meta.mr_url", "应为字符串（本地 / 通用 diff 模式可以留空）")
    for key in ("platform", "mr_label"):
        if key in meta and not isinstance(meta[key], str):
            fail(f"meta.{key}", "应为字符串")
    if not isinstance(meta.get("mr_iid"), int):
        fail("meta.mr_iid", "应为整数")
    stats = need(meta, "stats", "meta", dict)
    for key in ("files", "additions", "deletions", "commits"):
        if not isinstance(stats.get(key), int):
            fail(f"meta.stats.{key}", "应为整数")

    overview = need(data, "overview", "root", dict)
    check_text(need(overview, "one_liner", "overview", str), "overview.one_liner")
    problem = need(overview, "problem", "overview", dict)
    check_text(need(problem, "headline", "overview.problem", str), "overview.problem.headline")
    check_text(need(problem, "body", "overview.problem", str), "overview.problem.body")
    evidence = need(problem, "evidence", "overview.problem", list)
    for i, e in enumerate(evidence):
        check_text(need(e, "text", f"overview.problem.evidence[{i}]", str), f"overview.problem.evidence[{i}].text")
    solution = need(overview, "solution", "overview", list, nonempty=True)
    for i, s in enumerate(solution):
        check_text(s, f"overview.solution[{i}]")
    impact = need(overview, "impact", "overview", list, nonempty=True)
    for i, item in enumerate(impact):
        check_text(need(item, "area", f"overview.impact[{i}]", str), f"overview.impact[{i}].area")
        check_text(need(item, "detail", f"overview.impact[{i}]", str), f"overview.impact[{i}].detail")
        if item.get("level") not in LEVELS:
            fail(f"overview.impact[{i}].level", f"应为 {sorted(LEVELS)}")
    risk = need(overview, "risk", "overview", dict)
    check_text(need(risk, "level", "overview.risk", str), "overview.risk.level")
    for i, item in enumerate(need(risk, "items", "overview.risk", list, nonempty=True)):
        check_text(item, f"overview.risk.items[{i}]")

    features = need(data, "features", "root", list, nonempty=True)
    for i, f in enumerate(features):
        check_text(need(f, "title", f"features[{i}]", str), f"features[{i}].title")
        check_text(need(f, "detail", f"features[{i}]", str), f"features[{i}].detail")
        if f.get("status") not in STATUSES:
            fail(f"features[{i}].status", f"应为 {sorted(STATUSES)}")

    files = need(data, "files", "root", list, nonempty=True)
    file_paths = set()
    for i, f in enumerate(files):
        path = need(f, "path", f"files[{i}]", str, nonempty=True)
        file_paths.add(path)
        check_text(need(f, "summary", f"files[{i}]", str), f"files[{i}].summary")
        if f.get("role") not in ROLES:
            fail(f"files[{i}].role", f"应为 {sorted(ROLES)}")
        if f.get("change") not in CHANGES:
            fail(f"files[{i}].change", f"应为 {sorted(CHANGES)}")
        for key in ("additions", "deletions"):
            if not isinstance(f.get(key), int):
                fail(f"files[{i}].{key}", "应为整数")

    chain = need(data, "chain", "root", dict)
    check_text(need(chain, "summary", "chain", str), "chain.summary")
    nodes = need(chain, "nodes", "chain", list, nonempty=True)
    node_ids = set()
    for i, n in enumerate(nodes):
        nid = need(n, "id", f"chain.nodes[{i}]", str, nonempty=True)
        if nid in node_ids:
            fail(f"chain.nodes[{i}].id", f"重复的节点 id: {nid}")
        node_ids.add(nid)
        for key in ("lane", "label", "detail"):
            check_text(need(n, key, f"chain.nodes[{i}]", str), f"chain.nodes[{i}].{key}")
    edges = need(chain, "edges", "chain", list)
    for i, e in enumerate(edges):
        for key in ("from", "to"):
            ref = need(e, key, f"chain.edges[{i}]", str)
            if ref not in node_ids:
                fail(f"chain.edges[{i}].{key}", f"引用了不存在的节点 {ref}")

    design = need(data, "design", "root", dict)
    check_text(need(design, "summary", "design", str), "design.summary")
    decisions = need(design, "decisions", "design", list, nonempty=True)
    for i, d in enumerate(decisions):
        for key in ("question", "choice", "why"):
            check_text(need(d, key, f"design.decisions[{i}]", str), f"design.decisions[{i}].{key}")

    steps = need(data, "steps", "root", list, nonempty=True)
    step_ids = set()
    for i, s in enumerate(steps):
        sid = need(s, "id", f"steps[{i}]", str, nonempty=True)
        if not re.match(r"^[a-z][a-z0-9-]*$", sid):
            fail(f"steps[{i}].id", "只允许小写字母、数字、连字符，且以字母开头")
        if sid in step_ids:
            fail(f"steps[{i}].id", f"重复的步骤 id: {sid}")
        step_ids.add(sid)
        check_text(need(s, "title", f"steps[{i}]", str), f"steps[{i}].title")
        check_text(need(s, "goal", f"steps[{i}]", str), f"steps[{i}].goal")
        if s.get("file") and s["file"] not in file_paths:
            warnings.append(f"steps[{i}].file 未出现在 files[]: {s['file']}")
        snippets = s.get("snippets") or []
        if not snippets and not s.get("diff"):
            fail(f"steps[{i}]", "至少需要一个 snippets 或 diff")
        for j, sn in enumerate(snippets):
            check_text(need(sn, "code", f"steps[{i}].snippets[{j}]", str), f"steps[{i}].snippets[{j}].code")
        explain = s.get("explain") or []
        if not explain:
            warnings.append(f"steps[{i}] 没有 explain，读者可能不知道为什么这么改")
        for j, item in enumerate(explain):
            check_text(item, f"steps[{i}].explain[{j}]")

    database = need(data, "database", "root", dict)
    if not isinstance(database.get("has_change"), bool):
        fail("database.has_change", "应为布尔值")
    check_text(need(database, "headline", "database", str), "database.headline")
    check_text(need(database, "summary", "database", str), "database.summary")
    if database["has_change"] and not database.get("tables"):
        fail("database.tables", "has_change=true 时至少给出一个表变更")
    for i, t in enumerate(database.get("tables") or []):
        for key in ("name", "op", "ddl"):
            check_text(need(t, key, f"database.tables[{i}]", str), f"database.tables[{i}].{key}")

    tests = need(data, "tests", "root", dict)
    check_text(need(tests, "strategy", "tests", str), "tests.strategy")
    cases = need(tests, "cases", "tests", list, nonempty=True)
    for i, c in enumerate(cases):
        check_text(need(c, "name", f"tests.cases[{i}]", str), f"tests.cases[{i}].name")
        check_text(need(c, "covers", f"tests.cases[{i}]", str), f"tests.cases[{i}].covers")
        if c.get("type") not in TEST_TYPES:
            fail(f"tests.cases[{i}].type", f"应为 {sorted(TEST_TYPES)}")

    verify = need(data, "verify", "root", dict)
    check_text(need(verify, "environment", "verify", str), "verify.environment")
    steps_v = need(verify, "steps", "verify", list, nonempty=True)
    for i, s in enumerate(steps_v):
        check_text(need(s, "action", f"verify.steps[{i}]", str), f"verify.steps[{i}].action")
        check_text(need(s, "expect", f"verify.steps[{i}]", str), f"verify.steps[{i}].expect")

    for i, g in enumerate(data.get("glossary") or []):
        check_text(need(g, "term", f"glossary[{i}]", str), f"glossary[{i}].term")
        check_text(need(g, "desc", f"glossary[{i}]", str), f"glossary[{i}].desc")

    if len(steps) < 3:
        warnings.append(f"只有 {len(steps)} 个步骤，通常不足以讲清一条开发链路")
    changed = [f for f in files if f.get("change") != "context"]
    if len(changed) > len(steps) and len(steps) < len(changed):
        warnings.append(f"改动文件 {len(changed)} 个，但走读只有 {len(steps)} 步，确认是否漏讲")
    return warnings


def render(data: dict) -> str:
    if not TEMPLATE.is_file():
        raise SystemExit(f"模板不存在: {TEMPLATE}")
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"模板缺少占位符 {PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep the JSON valid inside <script> regardless of content.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace(PLACEHOLDER, payload, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description="把走读内容 JSON 渲染成单文件 HTML")
    ap.add_argument("content", help="content JSON 路径")
    ap.add_argument("--out", help="输出 HTML 路径（默认与 JSON 同名）")
    ap.add_argument("--open", action="store_true", help="渲染后用默认浏览器打开")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    path = Path(args.content)
    if not path.is_file():
        print(f"ERROR: 找不到 {path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: JSON 解析失败 {path}:{exc.lineno}:{exc.colno} {exc.msg}", file=sys.stderr)
        return 1

    try:
        warnings = validate(data)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

    if args.check:
        print(f"OK  {len(data['steps'])} steps, {len(data['files'])} files, {len(data['chain']['nodes'])} chain nodes")
        return 0

    html = render(data)
    out = Path(args.out) if args.out else path.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"OK  {out}  ({out.stat().st_size / 1024:.0f} KB, {len(data['steps'])} steps)")

    if args.open:
        import subprocess

        subprocess.run(["open", str(out)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
