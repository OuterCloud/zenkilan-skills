#!/usr/bin/env python3
"""Local two-ref comparison provider.

Covers platforms with no usable API (Gerrit, Bitbucket Server, code review by
email, a stash before pushing) and the case where you simply have a checkout:

    mr_fetch.py --local --base-ref main --head-ref feature/x --repo /path/to/repo

Only committed refs are compared; uncommitted working-tree changes are ignored
on purpose, so the walkthrough always describes something reproducible.
"""

from __future__ import annotations

import subprocess

from .base import Change, Commit, FetchError, Provider, Snapshot, split_unified_diff


def git(repo: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise FetchError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc.stdout


class LocalProvider(Provider):
    name = "local"
    web_name = "本地 git"

    def fetch(self) -> Snapshot:
        repo = self.ref.repo or "."
        base_ref = self.ref.base_ref or "master"
        head_ref = self.ref.head_ref or "HEAD"

        head_sha = git(repo, "rev-parse", "--verify", f"{head_ref}^{{commit}}").strip()
        try:
            base_sha = git(repo, "merge-base", base_ref, head_sha).strip()
        except FetchError as exc:
            raise FetchError(f"找不到 {base_ref!r} 与 {head_ref!r} 的共同祖先: {exc}") from exc

        diff = git(repo, "diff", "--no-color", "-M", "--full-index", f"{base_sha}..{head_sha}")
        changes = split_unified_diff(diff)

        commits: list[Commit] = []
        log = git(
            repo,
            "log",
            "--reverse",
            "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1f%b%x1e",
            f"{base_sha}..{head_sha}",
        )
        for record in log.split("\x1e"):
            fields = record.strip("\n").split("\x1f")
            if len(fields) < 5 or not fields[0]:
                continue
            commits.append(
                Commit(
                    short_id=fields[1],
                    title=fields[4],
                    message="\n".join(part for part in fields[4:] if part).strip(),
                    author_name=fields[2],
                    created_at=fields[3],
                )
            )

        title = commits[-1].title if commits else f"{base_ref}..{head_ref}"
        last = git(repo, "log", "-1", "--format=%an%x1f%ae", head_sha).strip().split("\x1f")
        author_name = last[0] if last else ""
        author_username = last[1].split("@")[0] if len(last) > 1 else ""

        return Snapshot(
            platform=self.name,
            host="",
            project=repo,
            number="",
            title=title,
            description="",
            state="local",
            author_username=author_username,
            author_name=author_name,
            source_branch=head_ref,
            target_branch=base_ref,
            sha=head_sha,
            base_sha=base_sha,
            web_url="",
            changes=changes,
            commits=commits,
            notes=["本地模式：没有 MR 评论、CI 状态和远程链接，标题取自最后一次 commit"],
        )
