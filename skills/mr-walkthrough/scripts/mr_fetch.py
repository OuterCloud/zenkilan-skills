#!/usr/bin/env python3
"""Fetch a merge request / pull request into a local working directory.

Supported sources (all normalized to the same snapshot layout):

    GitLab            https://host/group/project/-/merge_requests/128
    GitHub            https://github.com/owner/repo/pull/128   (or Enterprise host)
    Gitee             https://gitee.com/owner/repo/pulls/128
    Bitbucket Cloud   https://bitbucket.org/workspace/repo/pull-requests/128
    any diff URL      https://any.host/path/to/change.diff | .patch
    local refs        --base-ref main --head-ref feature/x

Produces a normalized snapshot that the mr-walkthrough skill can read:

    mr.json           MR metadata + stats (includes `platform`)
    changes.json      per-file diffs (unified diff text preserved)
    commits.json      commits in the MR
    discussions.json  human review comments (system notes stripped)
    history.json      recent git log for each changed file (when a local clone exists)
    context/<path>    full file content at the MR head sha (when a local clone exists)
    diff.patch        concatenated diff, handy for grep/less

Token resolution order:

    --token, then the platform's env vars (GITLAB_TOKEN, GITHUB_TOKEN/GH_TOKEN,
    GITEE_TOKEN, BITBUCKET_TOKEN, GENERIC_TOKEN), then `glab` / `gh` login state.

Usage:

    mr_fetch.py https://gitlab.example.com/acme/shop/-/merge_requests/128
    mr_fetch.py https://github.com/acme/shop/pull/128 --repo ~/code/shop
    mr_fetch.py acme/shop!128 --host gitlab.example.com
    mr_fetch.py owner/repo#128 --host github.com
    mr_fetch.py --local --base-ref main --head-ref feature/x --repo ~/code/shop
    mr_fetch.py https://any.host/changes/4711.diff

Exit codes: 0 ok, 1 usage/config/API error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from platforms import FetchError, Ref, login_hint, parse_ref, provider_for, resolve_token
from platforms.base import Snapshot


# --------------------------------------------------------------------------- git


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a command and return its stdout as a scalar: trailing newline stripped.

    Use this for values a caller will treat as one thing (a path, a SHA, a remote
    URL). git always terminates stdout with a newline, and feeding that newline
    into the next command silently corrupts it - `git -C "<path>\n"` fails with
    "cannot change to ...". Use run_raw instead when the bytes are file content.
    """
    return run_raw(cmd, cwd, check).strip()


def run_raw(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a command and return its stdout verbatim, newline included.

    For `git show` and friends, where the trailing newline is part of the file.
    """
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise FetchError(f"command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def detect_repo(path: Path | None) -> tuple[Path | None, str, str]:
    """Return (repo_root, host, project_path) from a local checkout."""
    cwd = path or Path.cwd()
    try:
        root = Path(run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]))
        remote = run(["git", "-C", str(root), "remote", "get-url", "origin"])
    except FetchError:
        return None, "", ""
    project, host = parse_remote(remote)
    return root, host, project


def parse_remote(remote: str) -> tuple[str, str]:
    import re

    match = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?$", remote)
    if match:
        return match.group(2), match.group(1)
    match = re.match(r"^https?://([^/]+)/(.+?)(?:\.git)?$", remote)
    if match:
        return match.group(2), match.group(1)
    return "", ""


# --------------------------------------------------------------------------- snapshot


def fetch_snapshot(args, repo_root: Path | None, repo_host: str, repo_project: str) -> tuple[Snapshot, Path | None]:
    local_mode = args.local or (not args.ref and args.base_ref and args.head_ref)
    if local_mode:
        if not (args.base_ref and args.head_ref):
            raise FetchError("本地模式需要同时给出 --base-ref 和 --head-ref")
        root = repo_root or (Path(args.repo) if args.repo else Path.cwd())
        ref = Ref(
            raw="",
            platform="local",
            host="",
            project=str(root),
            number="",
            repo=str(root),
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        return provider_for(ref, "").fetch(), root

    if not args.ref:
        raise FetchError("缺少 MR 引用：传 URL、group/project!128、owner/repo#128，或使用 --local")

    ref = parse_ref(
        args.ref,
        platform=args.platform,
        project=args.project,
        host=args.host,
        repo_host=repo_host,
        repo_project=repo_project,
    )
    token = resolve_token(ref.platform, ref.host, args.token)
    if not token and ref.platform not in ("generic", "local"):
        print(f"提示：没有找到 {ref.platform} token，按匿名访问处理（仅公开仓库适用）", file=sys.stderr)
    try:
        snapshot = provider_for(ref, token).fetch()
    except FetchError as exc:
        if not token and ref.platform not in ("generic", "local"):
            raise FetchError(f"{exc}\n{login_hint(ref.platform, ref.host)}") from exc
        raise

    if ref.platform not in ("local", "generic") and repo_project and repo_project != ref.project:
        print(
            f"注意：本地仓库 origin 是 {repo_project}，与目标 {ref.project} 不一致，将跳过 context 导出",
            file=sys.stderr,
        )
        repo_root = None
    return snapshot, repo_root


# --------------------------------------------------------------------------- git context


def safe_context_target(ctx_root: Path, path: str) -> Path | None:
    """Keep diff paths inside context/, even if the MR carries ../ or an absolute path."""
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    root = ctx_root.resolve()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def collect_context(repo: Path | None, snapshot: Snapshot, out_dir: Path) -> dict:
    header = {"sha": snapshot.sha, "files": [], "history": {}}
    if not repo or not snapshot.sha:
        return header
    try:
        run(["git", "-C", str(repo), "cat-file", "-e", f"{snapshot.sha}^{{commit}}"])
    except FetchError:
        print(f"本地缺少 commit {snapshot.sha[:8]}，尝试 fetch MR ref ...", flush=True)
        fetched = False
        for template in snapshot.fetch_refs:
            ref_name = template.format(n=snapshot.number)
            proc = subprocess.run(
                ["git", "-C", str(repo), "fetch", "origin", ref_name], capture_output=True, text=True
            )
            if proc.returncode == 0:
                fetched = True
                break
        if not fetched:
            print("fetch 后仍缺少该 commit，跳过 context（只能基于 diff 分析）", flush=True)
            return header
        try:
            run(["git", "-C", str(repo), "cat-file", "-e", f"{snapshot.sha}^{{commit}}"])
        except FetchError:
            print("fetch 后仍缺少该 commit，跳过 context（只能基于 diff 分析）", flush=True)
            return header

    ctx_root = out_dir / "context"
    for change in snapshot.changes:
        path = change.path
        if change.deleted_file or not change.diff:
            continue
        try:
            # run_raw: the trailing newline belongs to the file content.
            content = run_raw(["git", "-C", str(repo), "show", f"{snapshot.sha}:{path}"], check=False)
        except FetchError:
            continue
        if not content or "\x00" in content:
            continue
        target = safe_context_target(ctx_root, path)
        if target is None:
            print(f"跳过可疑路径（未写入 context）: {path}", file=sys.stderr)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        header["files"].append(path)

        history = run(
            [
                "git",
                "-C",
                str(repo),
                "log",
                "-3",
                "--date=short",
                "--format=%h\t%ad\t%s",
                "--",
                path,
            ],
            check=False,
        )
        if history:
            header["history"][path] = [line for line in history.splitlines() if line.strip()]
    return header


# --------------------------------------------------------------------------- output


def default_out_dir(snapshot: Snapshot) -> Path:
    if snapshot.platform == "local":
        label = f"local-{snapshot.target_branch or 'base'}-{snapshot.source_branch or 'head'}"
    else:
        label = f"{snapshot.project}-{snapshot.number}"
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in label.replace("/", "-"))
    return Path(".mr-walkthrough") / safe


def write_snapshot(snapshot: Snapshot, out_dir: Path, repo: Path | None, no_context: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    context = {"sha": snapshot.sha, "files": [], "history": {}}
    if not no_context:
        context = collect_context(repo, snapshot, out_dir)

    (out_dir / "mr.json").write_text(json.dumps(snapshot.mr_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "changes.json").write_text(
        json.dumps(snapshot.changes_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "commits.json").write_text(
        json.dumps(snapshot.commits_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "discussions.json").write_text(
        json.dumps(snapshot.discussions_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "diff.patch").write_text(snapshot.diff_patch(), encoding="utf-8")
    (out_dir / "history.json").write_text(
        json.dumps(context.get("history", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(context["files"])


def report(snapshot: Snapshot, out_dir: Path, context_files: int) -> None:
    stats = snapshot.stats
    if snapshot.platform == "local":
        label = f"{snapshot.target_branch}..{snapshot.source_branch}"
    elif snapshot.platform == "generic":
        label = snapshot.project
    elif snapshot.number:
        label = f"{snapshot.project}!{snapshot.number}"
    else:
        label = snapshot.project
    print("")
    print(f"{label}  {snapshot.title}")
    print(
        f"  {snapshot.platform}  {snapshot.state or '-'}  {snapshot.author_display()}  "
        f"{snapshot.source_branch or '-'} -> {snapshot.target_branch or '-'}"
    )
    print(f"  {stats['files']} files, +{stats['additions']} -{stats['deletions']}, {stats['commits']} commits")
    for note in snapshot.notes:
        print(f"  note: {note}")
    print("  changed:")
    for change in snapshot.changes:
        flag = "new" if change.new_file else "del" if change.deleted_file else "mod"
        print(f"    {flag:3s} +{change.additions:<4d} -{change.deletions:<4d} {change.path}")
    if context_files:
        print(f"  context: {context_files} files at {snapshot.sha[:8]}")
    print(f"  output: {out_dir}")


# --------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取 MR/PR 快照，供 mr-walkthrough 生成走读页面")
    parser.add_argument("ref", nargs="?", help="MR/PR URL、.diff 链接、group/project!128、owner/repo#128、128")
    parser.add_argument("--local", action="store_true", help="本地两分支对比模式（配 --base-ref / --head-ref）")
    parser.add_argument("--base-ref", help="本地模式：基线分支或 commit")
    parser.add_argument("--head-ref", help="本地模式：待走读的分支或 commit")
    parser.add_argument("--platform", help="强制平台（链接形态有歧义时用）")
    parser.add_argument("--project", help="项目路径，ref 只有编号时需要")
    parser.add_argument("--repo", help="本地仓库路径（默认当前目录）")
    parser.add_argument("--out", help="输出目录（默认 .mr-walkthrough/<project>-<number>）")
    parser.add_argument("--host", help="GitLab/GitHub/Gitee/Bitbucket 域名（简写引用没有域名时必填）")
    parser.add_argument("--token", help="访问 token（默认读平台环境变量或 glab/gh 登录态）")
    parser.add_argument("--no-context", action="store_true", help="不导出文件全文与 git history")
    args = parser.parse_args()

    try:
        repo_root, repo_host, repo_project = detect_repo(Path(args.repo) if args.repo else None)
        snapshot, repo_root = fetch_snapshot(args, repo_root, repo_host, repo_project)
        out_dir = Path(args.out) if args.out else default_out_dir(snapshot)
        context_files = write_snapshot(snapshot, out_dir, repo_root, args.no_context)
        report(snapshot, out_dir, context_files)
        return 0
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
