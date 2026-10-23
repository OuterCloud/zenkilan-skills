#!/usr/bin/env python3
"""Shared snapshot model, HTTP helper and provider contract for mr_fetch.

A provider turns one platform's MR/PR API into a Snapshot. The CLI then writes
one on-disk layout regardless of where the MR came from:

    mr.json  changes.json  commits.json  discussions.json
    history.json  diff.patch  context/<path>

Provider contract (see platforms/gitlab.py for a reference implementation):

    class XxxProvider(Provider):
        name = "xxx"            # registry key, also written to mr.json.platform
        web_name = "Xxx"        # display name, e.g. "GitHub"
        @classmethod
        def match(cls, url: str) -> bool
        def fetch(self) -> Snapshot

Keep every field optional except the ones the walkthrough really reads: title,
description, branches, head/base sha, changes. Missing commits/comments must not
fail the fetch; fill an empty list instead and say so in `notes`.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------- model


@dataclass
class Change:
    """One changed file. `diff` is the unified diff body without the `diff --git` header."""

    old_path: str
    new_path: str
    diff: str = ""
    new_file: bool = False
    deleted_file: bool = False
    renamed_file: bool = False
    too_large: bool = False

    @property
    def path(self) -> str:
        return self.new_path or self.old_path

    @property
    def additions(self) -> int:
        return _count(self.diff, "+")

    @property
    def deletions(self) -> int:
        return _count(self.diff, "-")

    def as_dict(self) -> dict:
        return {
            "old_path": self.old_path,
            "new_path": self.new_path,
            "new_file": self.new_file,
            "deleted_file": self.deleted_file,
            "renamed_file": self.renamed_file,
            "additions": self.additions,
            "deletions": self.deletions,
            "diff": self.diff,
            "too_large": self.too_large or self.diff == "",
        }


def _count(diff: str, sign: str) -> int:
    total = 0
    for line in diff.splitlines():
        if line.startswith(sign) and not line.startswith(sign * 3):
            total += 1
    return total


@dataclass
class Commit:
    short_id: str = ""
    title: str = ""
    message: str = ""
    author_name: str = ""
    created_at: str = ""

    def as_dict(self) -> dict:
        return {
            "short_id": self.short_id,
            "title": self.title,
            "message": self.message,
            "author_name": self.author_name,
            "created_at": self.created_at,
        }


@dataclass
class Note:
    id: str = ""
    author: str = ""
    body: str = ""
    created_at: str = ""
    system: bool = False
    resolvable: bool = False
    resolved: bool = False
    file: str = ""
    line: int | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "body": self.body,
            "created_at": self.created_at,
            "system": self.system,
            "resolvable": self.resolvable,
            "resolved": self.resolved,
            "file": self.file,
            "line": self.line,
        }


@dataclass
class Discussion:
    id: str = ""
    notes: list[Note] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"id": self.id, "notes": [n.as_dict() for n in self.notes]}


@dataclass
class Snapshot:
    platform: str
    host: str
    project: str
    number: str
    title: str = ""
    description: str = ""
    state: str = ""
    draft: bool = False
    author_username: str = ""
    author_name: str = ""
    source_branch: str = ""
    target_branch: str = ""
    sha: str = ""
    base_sha: str = ""
    web_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    merged_at: str = ""
    labels: list[str] = field(default_factory=list)
    notes_count: int = 0
    has_conflicts: bool = False
    changes: list[Change] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    discussions: list[Discussion] = field(default_factory=list)
    pipeline: dict = field(default_factory=dict)
    author_label: str = ""
    notes: list[str] = field(default_factory=list)
    # Remote refs to fetch when the head commit is missing locally, e.g.
    # "refs/merge-requests/{n}/head". `{n}` is replaced with the MR number.
    fetch_refs: list[str] = field(default_factory=list)

    @property
    def stats(self) -> dict:
        return {
            "files": len(self.changes),
            "additions": sum(c.additions for c in self.changes),
            "deletions": sum(c.deletions for c in self.changes),
            "commits": len(self.commits),
        }

    def author_display(self) -> str:
        if self.author_label:
            return self.author_label
        if self.author_username and self.author_name:
            return f"{self.author_name} (@{self.author_username})"
        return self.author_name or self.author_username or "unknown"

    def mr_json(self) -> dict:
        return {
            "platform": self.platform,
            "host": self.host,
            "project_path": self.project,
            "project_id": None,
            "iid": self.number,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "draft": self.draft,
            "author": {"username": self.author_username, "name": self.author_name},
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "sha": self.sha,
            "base_sha": self.base_sha,
            "web_url": self.web_url,
            "created_at": self.created_at or None,
            "updated_at": self.updated_at or None,
            "merged_at": self.merged_at or None,
            "labels": self.labels,
            "notes_count": self.notes_count,
            "has_conflicts": self.has_conflicts,
            "stats": self.stats,
            "pipeline": {"status": self.pipeline.get("status", ""), "web_url": self.pipeline.get("web_url", "")},
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": self.notes,
        }

    def changes_json(self) -> list[dict]:
        return [c.as_dict() for c in self.changes]

    def commits_json(self) -> list[dict]:
        return [c.as_dict() for c in self.commits]

    def discussions_json(self) -> list[dict]:
        return [d.as_dict() for d in self.discussions if d.notes]

    def diff_patch(self) -> str:
        return "\n".join(f"# {c.path}\n{c.diff}" for c in self.changes) + "\n"


# --------------------------------------------------------------------------- http


SENSITIVE_QUERY_KEYS = ("access_token", "private_token", "token", "client_secret", "api_key", "apikey")


def redact_url(url: str) -> str:
    """Mask credentials that platforms put in the query string (Gitee token, GitLab private_token).

    Every error message goes through this: a leaked token in a terminal log is
    worse than a less readable URL.
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    masked = [(key, "***" if key.lower() in SENSITIVE_QUERY_KEYS else value) for key, value in pairs]
    query = urllib.parse.urlencode(masked)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class Http:
    """Tiny stdlib HTTP client. Auth is injected as headers by the provider."""

    def __init__(self, headers: dict[str, str] | None = None, timeout: int = 60):
        self.headers = {"User-Agent": "mr-walkthrough/1.0", **(headers or {})}
        self.timeout = timeout

    def request(self, url: str, params: dict[str, str] | None = None, accept: str | None = None):
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = dict(self.headers)
        if accept:
            headers["Accept"] = accept
        headers.setdefault("Accept", "application/json")
        req = urllib.request.Request(url, headers=headers)
        shown = redact_url(url)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            hint = "（token 无效或权限不足）" if exc.code in (401, 403) else ""
            raise FetchError(f"GET {shown} -> HTTP {exc.code}{hint}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise FetchError(f"GET {shown} 失败: {exc.reason}") from exc

    def json(self, url: str, params: dict[str, str] | None = None):
        return self.json_with_headers(url, params)[0]

    def json_with_headers(self, url: str, params: dict[str, str] | None = None):
        body, headers = self.request(url, params)
        try:
            return json.loads(body), headers
        except json.JSONDecodeError as exc:
            raise FetchError(f"GET {redact_url(url)} 返回的不是 JSON: {body[:200]}") from exc

    def text(self, url: str, params: dict[str, str] | None = None, accept: str = "text/plain") -> str:
        return self.request(url, params, accept)[0]

    def paged(self, url: str, params: dict[str, str] | None = None, page_param: str = "page",
              next_header: str = "x-next-page", list_key: str | None = None) -> list:
        """Offset pagination where the next page number comes back in a header.

        Works for GitLab (`x-next-page`) and anything similar. Gitee/Bitbucket use
        their own loops because they page differently.
        """
        items: list = []
        params = dict(params or {})
        page = 1
        while True:
            params[page_param] = str(page)
            data, headers = self.json_with_headers(url, params)
            chunk = _as_list(data, list_key)
            items.extend(chunk)
            nxt = None
            for key, value in headers.items():
                if key.lower() == next_header.lower():
                    nxt = value
                    break
            if not nxt:
                break
            page = int(nxt)
        return items

    def paged_by_link(self, url: str, params: dict[str, str] | None = None, list_key: str | None = None) -> list:
        """GitHub style: next URL arrives in the `Link` header."""
        items: list = []
        next_url: str | None = url
        next_params = dict(params or {})
        while next_url:
            data, headers = self.json_with_headers(next_url, next_params)
            items.extend(_as_list(data, list_key))
            link = ""
            for key, value in headers.items():
                if key.lower() == "link":
                    link = value
                    break
            match = re.search(r'<([^>]+)>\s*;\s*rel="next"', link or "")
            next_url = match.group(1) if match else None
            next_params = {}
        return items


def _as_list(data, list_key: str | None) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if list_key and isinstance(data.get(list_key), list):
            return data[list_key]
        for key in ("changes", "diffs", "values", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


# --------------------------------------------------------------------------- provider base


@dataclass
class Ref:
    """A parsed MR/PR reference: enough to build both the web and the API URL."""

    raw: str
    platform: str
    host: str
    project: str
    number: str
    url: str = ""
    scheme: str = "https"
    web_base: str = ""
    # Local mode only: the checkout to read and the two refs to compare.
    repo: str = ""
    base_ref: str = ""
    head_ref: str = ""


class Provider:
    name = ""
    web_name = ""

    def __init__(self, ref: Ref, token: str = ""):
        self.ref = ref
        self.token = token

    @classmethod
    def match(cls, url: str) -> bool:
        return False

    def fetch(self) -> Snapshot:
        raise NotImplementedError

    # -- helpers shared by subclasses -------------------------------------

    def require(self, value, what: str):
        if value in (None, "", [], {}):
            raise FetchError(f"{self.web_name or self.name} 返回的数据缺少 {what}，无法继续")
        return value

    def api_url(self, path: str) -> str:
        return f"{self.ref.scheme}://{self.ref.host}{path}"

    def empty_snapshot(self, **kwargs) -> Snapshot:
        base = {
            "platform": self.name,
            "host": self.ref.host,
            "project": self.ref.project,
            "number": self.ref.number,
            "web_url": self.ref.url,
        }
        base.update(kwargs)
        return Snapshot(**base)


def strip_ref_prefix(number: str) -> str:
    return number.lstrip("!#")


# --------------------------------------------------------------------------- diff parsing

DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+?)$")
# git quotes paths that contain spaces or control characters.
DIFF_GIT_QUOTED_RE = re.compile(r'^diff --git "a/(?P<old>.+)" "b/(?P<new>.+)"$')
DEV_NULL = ("/dev/null",)


def _unquote_path(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def split_unified_diff(text: str) -> list[Change]:
    """Split one unified diff into per-file Changes, keeping hunk bodies verbatim.

    Used by providers that only receive a diff (Bitbucket's /diff, any .diff URL).
    The `diff --git` header is dropped from `Change.diff`, so line counts match a
    hunk-only view. Header lines (index/mode/---/+++) are dropped too, except the
    new/deleted/renamed markers we need.
    """
    changes: list[Change] = []
    current: Change | None = None
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\n")
        match = DIFF_GIT_QUOTED_RE.match(line) or DIFF_GIT_RE.match(line)
        if match:
            if current is not None:
                changes.append(current)
            current = Change(old_path=match.group("old"), new_path=match.group("new"))
            continue
        if current is None:
            continue
        if line.startswith("new file mode"):
            current.new_file = True
        elif line.startswith("deleted file mode"):
            current.deleted_file = True
        elif line.startswith("rename from "):
            current.renamed_file = True
            current.old_path = _unquote_path(line[len("rename from "):])
        elif line.startswith("rename to "):
            current.renamed_file = True
            current.new_path = _unquote_path(line[len("rename to "):])
        elif line.startswith("--- ") and line[4:].strip() in DEV_NULL:
            current.new_file = True
        elif line.startswith("+++ ") and line[4:].strip() in DEV_NULL:
            current.deleted_file = True
        elif line.startswith("@@") or (current.diff and line[:1] in (" ", "+", "-", "\\")):
            current.diff += raw
    if current is not None:
        changes.append(current)
    return changes
