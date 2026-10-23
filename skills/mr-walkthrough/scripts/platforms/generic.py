#!/usr/bin/env python3
"""Generic provider: turn any .diff / .patch URL into a snapshot.

This is the long tail escape hatch: Gerrit, Bitbucket Server, an internal review
tool, a patch attached to a ticket. Metadata is whatever the patch carries, so
the walkthrough must state that line numbers and intent were not cross-checked
against the platform.

Works because GitLab (`/-/merge_requests/128.diff`) and GitHub (`/pull/128.diff`)
both expose such URLs, and most other tools follow the same convention.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .base import Change, Commit, FetchError, Http, Provider, Ref, Snapshot, split_unified_diff

PATCH_START_RE = re.compile(r"^From ([0-9a-f]{7,40}) ", re.M)
SUBJECT_RE = re.compile(r"^Subject:\s*(?P<subject>.+)$", re.M)
FROM_RE = re.compile(r"^From:\s*(?P<name>.+?)\s*<(?P<email>[^>]+)>\s*$", re.M)
DATE_RE = re.compile(r"^Date:\s*(?P<date>.+)$", re.M)
PATCH_PREFIX_RE = re.compile(r"^\s*\[PATCH[^\]]*\]\s*", re.I)
NUMBER_IN_URL_RE = re.compile(r"/(?:merge_requests|pulls?|pull-requests)/(\d+)")


class GenericProvider(Provider):
    name = "generic"
    web_name = "通用 diff"

    def __init__(self, ref: Ref, token: str = ""):
        super().__init__(ref, token)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.api = Http(headers)

    @classmethod
    def match(cls, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(".diff") or path.endswith(".patch")

    def fetch(self) -> Snapshot:
        try:
            payload = self.api.text(self.ref.url, accept="text/plain, application/x-patch, */*")
        except FetchError as exc:
            raise FetchError(
                f"拉取 diff 失败: {exc}\n这个链接可能需要登录：改用对应平台的 API 模式，"
                f"或设置 GENERIC_TOKEN"
            ) from exc
        if not payload.strip():
            raise FetchError(f"链接返回空内容: {self.ref.url}")

        changes = split_unified_diff(payload)
        if not changes:
            # Not a git-style diff: keep it as one opaque change so the walkthrough
            # still has something to read, and say so.
            changes = [Change(old_path=self._guess_path(), new_path=self._guess_path(), diff=payload)]

        commits = self._commits(payload)
        title = commits[0].title if commits else (self.ref.project or self._guess_path())
        web_url = re.sub(r"\.(diff|patch)$", "", self.ref.url)
        if not web_url.startswith(("http://", "https://")):
            web_url = ""
        number_match = NUMBER_IN_URL_RE.search(self.ref.url)

        return Snapshot(
            platform=self.name,
            host=self.ref.host,
            project=self.ref.project,
            number=number_match.group(1) if number_match else "",
            title=title,
            description="",
            state="",
            author_name=commits[0].author_name if commits else "",
            source_branch="",
            target_branch="",
            web_url=web_url,
            changes=changes,
            commits=commits,
            notes=[
                "通用 diff 模式：只有 diff 本身，没有标题描述、评论、CI 状态和 commit 列表（.patch 除外），"
                "行号未与平台版本交叉核对",
            ],
        )

    def _guess_path(self) -> str:
        name = urlparse(self.ref.url).path.rsplit("/", 1)[-1]
        return re.sub(r"\.(diff|patch)$", "", name) or "unknown"

    def _commits(self, payload: str) -> list[Commit]:
        """Parse `From <sha>` / Subject / Date blocks that .patch mails carry."""
        starts = [m.start() for m in PATCH_START_RE.finditer(payload)]
        if not starts:
            return []
        commits: list[Commit] = []
        for index, start in enumerate(starts):
            block = payload[start:starts[index + 1] if index + 1 < len(starts) else len(payload)]
            sha = PATCH_START_RE.match(block).group(1)
            subject = SUBJECT_RE.search(block)
            author = FROM_RE.search(block)
            date = DATE_RE.search(block)
            title = PATCH_PREFIX_RE.sub("", subject.group("subject").strip()) if subject else ""
            body_start = block.find("\n\n")
            body = block[body_start + 2:].split("\n---\n", 1)[0].strip() if body_start != -1 else ""
            commits.append(
                Commit(
                    short_id=sha[:7],
                    title=title,
                    message=(title + ("\n\n" + body if body else "")).strip(),
                    author_name=author.group("name").strip() if author else "",
                    created_at=date.group("date").strip() if date else "",
                )
            )
        return commits
