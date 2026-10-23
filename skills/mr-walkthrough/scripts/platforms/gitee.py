#!/usr/bin/env python3
"""Gitee provider (gitee.com OpenAPI v5).

API: https://gitee.com/api/v5/swagger
Auth: access_token query parameter (personal access token, GITEE_TOKEN).

Gitee pages with page/per_page and sends no next-page header, so every list
endpoint is walked until a short page comes back. Missing patch bodies, commits
or comments degrade into notes instead of failing the whole fetch.
"""

from __future__ import annotations

import re
import urllib.parse

from .base import Change, Commit, Discussion, FetchError, Http, Note, Provider, Ref, Snapshot

GITEE_URL_RE = re.compile(r"^https?://(?:www\.)?gitee\.com/[^/]+/[^/]+/pulls?/\d+")

STATE_MAP = {
    "merged": "merged",
    "open": "opened",
    "opened": "opened",
    "closed": "closed",
    "progressing": "closed",
    "rejected": "closed",
}


class GiteeProvider(Provider):
    name = "gitee"
    web_name = "Gitee"

    per_page = 100
    max_pages = 100

    def __init__(self, ref: Ref, token: str = ""):
        super().__init__(ref, token)
        self.api = Http()
        self.base = "https://gitee.com/api/v5"
        self.project_enc = urllib.parse.quote(ref.project.strip("/"), safe="/")
        self.notes: list[str] = []

    @classmethod
    def match(cls, url: str) -> bool:
        return bool(GITEE_URL_RE.match((url or "").strip()))

    def fetch(self) -> Snapshot:
        mr = self._get(self._pull_path())
        head = mr.get("head") or {}
        base = mr.get("base") or {}
        user = mr.get("user") or {}

        return Snapshot(
            platform=self.name,
            host=self.ref.host,
            project=self.ref.project,
            number=str(self.ref.number),
            title=mr.get("title") or "",
            description=mr.get("body") or "",
            state=_state(mr.get("state")),
            author_username=user.get("login") or "",
            author_name=user.get("name") or user.get("login") or "",
            source_branch=head.get("ref") or "",
            target_branch=base.get("ref") or "",
            sha=head.get("sha") or "",
            base_sha=base.get("sha") or "",
            web_url=mr.get("html_url") or self.ref.url,
            created_at=mr.get("created_at") or "",
            updated_at=mr.get("updated_at") or "",
            merged_at=mr.get("merged_at") or "",
            labels=_labels(mr.get("labels")),
            notes_count=_as_int(mr.get("comments")),
            changes=self._changes(),
            commits=self._commits(),
            discussions=self._discussions(),
            notes=self.notes,
        )

    # -- endpoints ---------------------------------------------------------

    def _pull_path(self) -> str:
        return f"/repos/{self.project_enc}/pulls/{self.ref.number}"

    def _changes(self) -> list[Change]:
        try:
            raw = self._paged(f"{self._pull_path()}/files")
        except FetchError as exc:
            self.notes.append(f"拉取变更文件列表失败，变更列表留空: {exc}")
            return []
        return [_change(item) for item in raw if isinstance(item, dict)]

    def _commits(self) -> list[Commit]:
        try:
            raw = self._paged(f"{self._pull_path()}/commits")
        except FetchError as exc:
            self.notes.append(f"拉取提交列表失败，提交列表留空: {exc}")
            return []
        return [_commit(item) for item in raw if isinstance(item, dict)]

    def _discussions(self) -> list[Discussion]:
        out: list[Discussion] = []

        try:
            review_comments = self._paged(f"{self._pull_path()}/comments")
        except FetchError as exc:
            self.notes.append(f"拉取 Pull Request 行内评论失败，已跳过: {exc}")
            review_comments = []
        for item in review_comments:
            if isinstance(item, dict):
                out.append(Discussion(id=f"review-{item.get('id', '')}", notes=[_note(item)]))

        try:
            issue_comments = self._paged(f"/repos/{self.project_enc}/issues/{self.ref.number}/comments")
        except FetchError as exc:
            self.notes.append(f"拉取 Issue 评论失败，已跳过: {exc}")
            issue_comments = []
        for item in issue_comments:
            if isinstance(item, dict):
                out.append(Discussion(id=f"issue-{item.get('id', '')}", notes=[_note(item)]))

        return out

    # -- transport ---------------------------------------------------------

    def _get(self, path: str, extra: dict | None = None):
        url = f"{self.base}{path}"
        try:
            return self.api.json(url, self._params(extra))
        except FetchError as exc:
            # Http puts the whole URL (query included) into its message; the
            # access_token must never reach a log or a traceback.
            raise FetchError(self._redact(str(exc))) from exc

    def _params(self, extra: dict | None = None) -> dict:
        params = dict(extra or {})
        if self.token:
            params["access_token"] = self.token
        return params

    def _redact(self, text: str) -> str:
        if self.token:
            text = text.replace(self.token, "***")
        return re.sub(r"(access_token=)[^&\s]+", r"\1***", text)

    def _paged(self, path: str) -> list:
        items: list = []
        page = 1
        while True:
            data = self._get(path, {"page": page, "per_page": self.per_page})
            if not isinstance(data, list):
                self.notes.append(f"接口返回的不是列表，按空数据处理: {path}")
                break
            if not data:
                break
            items.extend(data)
            if len(data) < self.per_page:
                break
            if page >= self.max_pages:
                self.notes.append(f"分页达到上限 {self.max_pages} 页，后面的数据没有继续拉取: {path}")
                break
            page += 1
        return items


# --------------------------------------------------------------------------- mapping


def _state(raw) -> str:
    value = raw.strip().lower() if isinstance(raw, str) else ""
    if not value:
        return ""
    return STATE_MAP.get(value, value)


def _labels(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if name:
            out.append(str(name))
    return out


def _change(item: dict) -> Change:
    filename = item.get("filename") or ""
    diff = item.get("patch") or item.get("diff") or ""
    status = (item.get("status") or "").strip().lower()
    return Change(
        old_path=item.get("previous_filename") or filename,
        new_path=filename,
        diff=diff,
        new_file=status == "added",
        deleted_file=status in ("removed", "deleted"),
        renamed_file=status == "renamed",
        too_large=diff == "",
    )


def _commit(item: dict) -> Commit:
    commit = item.get("commit") or {}
    message = commit.get("message") or ""
    author = commit.get("author") or {}
    return Commit(
        short_id=(item.get("sha") or "")[:7],
        title=message.strip().splitlines()[0] if message.strip() else "",
        message=message,
        author_name=author.get("name") or "",
        created_at=author.get("date") or "",
    )


def _note(item: dict) -> Note:
    user = item.get("user") or {}
    return Note(
        id=str(item.get("id", "")),
        author=user.get("login") or "",
        body=(item.get("body") or "").strip(),
        created_at=item.get("created_at") or "",
        file=item.get("path") or "",
        line=_line(item),
    )


def _line(item: dict) -> int | None:
    for key in ("position", "line"):
        value = _as_int(item.get(key), default=None)
        if value is not None:
            return value
    return None


def _as_int(value, default=0):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
