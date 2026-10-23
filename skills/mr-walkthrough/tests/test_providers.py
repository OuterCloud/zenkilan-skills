#!/usr/bin/env python3
"""Fixture tests for the mr-walkthrough platform adapters.

Run from skills/mr-walkthrough with unittest discovery or directly. Every
provider talks to an in-memory FakeHttp, so the suite needs no network access
and no real credentials.
"""

from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from platforms import FetchError, Ref, parse_ref  # noqa: E402
from platforms.base import Change, Commit, Snapshot, redact_url, split_unified_diff  # noqa: E402
from platforms.bitbucket import BitbucketProvider  # noqa: E402
from platforms.gitee import GiteeProvider  # noqa: E402
from platforms.github import GitHubProvider  # noqa: E402

TOKEN = "tok-123"
MISSING = object()


class FakeHttp:
    """In-memory Http replacement keyed by exact URL or longest URL prefix.

    A fixture may be a payload, an Exception instance or a callable that takes
    (url, params). Every public method records ("kind", url, params) in calls.
    """

    def __init__(self):
        self._exact = {}
        self._prefixes = []
        self.calls = []

    def add(self, url, payload):
        self._exact[url] = payload
        return self

    def add_prefix(self, prefix, payload):
        self._prefixes.append((prefix, payload))
        self._prefixes.sort(key=lambda entry: len(entry[0]), reverse=True)
        return self

    def json(self, url, params=None):
        self.calls.append(("json", url, dict(params or {})))
        return self._resolve(url, params)

    def paged_by_link(self, url, params=None, list_key=None):
        self.calls.append(("paged", url, dict(params or {})))
        return self._resolve(url, params)

    def text(self, url, params=None, accept="text/plain"):
        self.calls.append(("text", url, dict(params or {})))
        return self._resolve(url, params)

    def urls(self):
        return [url for _, url, _ in self.calls]

    def _resolve(self, url, params):
        payload = self._exact.get(url, MISSING)
        if payload is MISSING:
            for prefix, candidate in self._prefixes:
                if url.startswith(prefix):
                    payload = candidate
                    break
        if payload is MISSING:
            raise AssertionError(f"unexpected URL: {url}")
        if isinstance(payload, Exception):
            raise payload
        if callable(payload):
            payload = payload(url, params or {})
        return copy.deepcopy(payload)


def page_route(pages):
    def route(url, params):
        page = int(params.get("page", 1))
        return pages[page - 1] if page <= len(pages) else []

    return route


# --------------------------------------------------------------------------- GitHub


GITHUB_API = "https://api.github.com"
GITHUB_PROJECT = "acme/shop"
GITHUB_PULL_URL = f"{GITHUB_API}/repos/{GITHUB_PROJECT}/pulls/128"
GITHUB_FILES_URL = f"{GITHUB_PULL_URL}/files"
GITHUB_COMMITS_URL = f"{GITHUB_PULL_URL}/commits"
GITHUB_REVIEWS_URL = f"{GITHUB_PULL_URL}/comments"
GITHUB_ISSUE_COMMENTS_URL = f"{GITHUB_API}/repos/{GITHUB_PROJECT}/issues/128/comments"
GITHUB_WEB_URL = "https://github.com/acme/shop/pull/128"


def github_pull(state="open", merged_at=None):
    return {
        "number": 128,
        "title": "Add checkout flow",
        "body": "Wire the cart to the new checkout page.",
        "state": state,
        "draft": False,
        "merged_at": merged_at,
        "user": {"login": "alice", "name": None},
        "head": {"ref": "feature/checkout", "sha": "headsha0123456789"},
        "base": {"ref": "main", "sha": "basesha0123456789"},
        "html_url": GITHUB_WEB_URL,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "labels": [{"name": "feature"}, {"name": "checkout"}],
        "comments": 2,
        "review_comments": 5,
        "mergeable": True,
    }


GITHUB_FILES = [
    {
        "filename": "src/checkout.py",
        "status": "added",
        "patch": "@@ -0,0 +1,2 @@\n+print('new')\n+print('file')",
    },
    {
        "filename": "src/new_name.py",
        "previous_filename": "src/old_name.py",
        "status": "renamed",
        "patch": "@@ -1 +1 @@\n-old\n+new",
    },
    {
        "filename": "src/legacy.py",
        "status": "removed",
        "patch": "@@ -1,1 +0,0 @@\n-print('gone')",
    },
    {
        "filename": "assets/logo.png",
        "status": "modified",
    },
]

GITHUB_COMMITS = [
    {
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "commit": {
            "message": "feat: add checkout page\n\nWire the cart to checkout.",
            "author": {"name": "Alice Zhang", "date": "2026-10-01T11:00:00Z"},
        },
    },
]

GITHUB_REVIEWS = [
    {
        "id": 501,
        "user": {"login": "reviewer1"},
        "body": "Rename this helper.",
        "created_at": "2026-10-01T12:00:00Z",
        "path": "src/checkout.py",
        "line": 12,
        "original_line": 10,
    },
    {
        "id": 502,
        "user": {"login": "reviewer2"},
        "body": "Stale thread.",
        "created_at": "2026-10-01T13:00:00Z",
        "path": "src/legacy.py",
        "line": None,
        "original_line": 7,
    },
]

GITHUB_ISSUE_COMMENTS = [
    {
        "id": 900,
        "user": {"login": "alice"},
        "body": "Thanks, merging soon.",
        "created_at": "2026-10-02T09:00:00Z",
    },
]


def github_fake(pull=None, fail=()):
    fake = FakeHttp()
    fake.add(GITHUB_PULL_URL, pull if pull is not None else github_pull())
    fake.add(GITHUB_FILES_URL, GITHUB_FILES)
    fake.add(GITHUB_COMMITS_URL, GITHUB_COMMITS)
    fake.add(GITHUB_REVIEWS_URL, GITHUB_REVIEWS)
    fake.add(GITHUB_ISSUE_COMMENTS_URL, GITHUB_ISSUE_COMMENTS)
    for url in fail:
        fake.add(url, FetchError(f"GET {url} -> HTTP 403"))
    return fake


def github_provider(fake=None):
    ref = Ref(
        raw=GITHUB_WEB_URL,
        platform="github",
        host="github.com",
        project=GITHUB_PROJECT,
        number="128",
        url=GITHUB_WEB_URL,
    )
    provider = GitHubProvider(ref, token=TOKEN)
    provider.api = fake if fake is not None else github_fake()
    return provider


# --------------------------------------------------------------------------- Gitee


GITEE_API = "https://gitee.com/api/v5"
GITEE_PROJECT = "acme/shop"
GITEE_PULL_PATH = f"/repos/{GITEE_PROJECT}/pulls/128"
GITEE_FILES_PATH = f"{GITEE_PULL_PATH}/files"
GITEE_COMMITS_PATH = f"{GITEE_PULL_PATH}/commits"
GITEE_REVIEW_PATH = f"{GITEE_PULL_PATH}/comments"
GITEE_ISSUE_PATH = f"/repos/{GITEE_PROJECT}/issues/128/comments"
GITEE_WEB_URL = "https://gitee.com/acme/shop/pulls/128"

GITEE_HEAD_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
GITEE_BASE_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def gitee_pull(state="open", **overrides):
    data = {
        "title": "Add checkout page",
        "body": "Split checkout into two steps",
        "state": state,
        "user": {"login": "alice", "name": "Alice Zhang"},
        "head": {"ref": "feature/checkout", "sha": GITEE_HEAD_SHA},
        "base": {"ref": "master", "sha": GITEE_BASE_SHA},
        "html_url": GITEE_WEB_URL,
        "created_at": "2026-10-01T10:00:00+08:00",
        "updated_at": "2026-10-02T11:00:00+08:00",
        "merged_at": None,
        "labels": [{"name": "enhancement"}, {"name": "backend"}],
        "comments": 7,
    }
    data.update(overrides)
    return data


def gitee_fake(pull=None, files=None, commits=None, review=None, issue=None, errors=None):
    fake = FakeHttp()
    fake.add(GITEE_API + GITEE_PULL_PATH, pull if pull is not None else gitee_pull())
    fake.add(GITEE_API + GITEE_FILES_PATH, page_route(files or [[]]))
    fake.add(GITEE_API + GITEE_COMMITS_PATH, page_route(commits or [[]]))
    fake.add(GITEE_API + GITEE_REVIEW_PATH, page_route(review or [[]]))
    fake.add(GITEE_API + GITEE_ISSUE_PATH, page_route(issue or [[]]))
    for path, error in (errors or {}).items():
        fake.add(GITEE_API + path, error)
    return fake


def gitee_provider(per_page=100, fake=None, **kwargs):
    ref = Ref(
        raw=GITEE_WEB_URL,
        platform="gitee",
        host="gitee.com",
        project=GITEE_PROJECT,
        number="128",
        url=GITEE_WEB_URL,
    )
    provider = GiteeProvider(ref, token=TOKEN)
    provider.api = fake if fake is not None else gitee_fake(**kwargs)
    provider.per_page = per_page
    return provider


# --------------------------------------------------------------------------- Bitbucket


BITBUCKET_API = "https://api.bitbucket.org/2.0/repositories/acme/shop"
BITBUCKET_PR_URL = f"{BITBUCKET_API}/pullrequests/128"
BITBUCKET_WEB_URL = "https://bitbucket.org/acme/shop/pull-requests/128"

BITBUCKET_DIFF = """diff --git a/docs/guide.md b/docs/guide.md
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/docs/guide.md
@@ -0,0 +1,2 @@
+# Guide
+hello
diff --git a/app/main.py b/app/main.py
index 2222222..3333333 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,4 @@
 import os
-print("old")
+print("new")
+print("extra")
 def main():
diff --git a/legacy/old_module.py b/legacy/old_module.py
deleted file mode 100644
index 4444444..0000000
--- a/legacy/old_module.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("legacy")
-pass
diff --git a/app/config.yaml b/app/settings.yaml
similarity index 90%
rename from app/config.yaml
rename to app/settings.yaml
index 5555555..6666666 100644
--- a/app/config.yaml
+++ b/app/settings.yaml
@@ -1,1 +1,1 @@
-name: shop
+name: shop-renamed
"""

BITBUCKET_COMMITS_PAGE_1 = {
    "values": [
        {
            "hash": "abcdef1234567890",
            "message": "feat: add guide\n\nmore detail",
            "author": {"user": {"display_name": "Alice Zhang"}},
            "date": "2026-01-02T03:04:05+00:00",
        }
    ],
    "next": f"{BITBUCKET_PR_URL}/commits?page=2",
}
BITBUCKET_COMMITS_PAGE_2 = {
    "values": [
        {
            "hash": "1234567890abcdef",
            "message": "fix: rename config",
            "author": {"user": {"display_name": "Bob Li"}},
            "date": "2026-01-03T04:05:06+00:00",
        }
    ],
    "next": None,
}
BITBUCKET_COMMENTS_PAGE_1 = {
    "values": [
        {
            "id": 1001,
            "user": {"display_name": "Carol"},
            "content": {"raw": "Looks good"},
            "created_on": "2026-01-06T00:00:00+00:00",
            "inline": {"path": "app/main.py", "to": 12},
        },
        {
            "id": 1002,
            "user": {"display_name": "Dan"},
            "content": {"raw": "deleted comment"},
            "created_on": "2026-01-06T00:00:01+00:00",
            "deleted": True,
        },
    ],
    "next": f"{BITBUCKET_PR_URL}/comments?page=2",
}
BITBUCKET_COMMENTS_PAGE_2 = {
    "values": [
        {
            "id": 1003,
            "user": {"display_name": "Eve"},
            "content": {"raw": "This can be improved"},
            "created_on": "2026-01-06T00:00:02+00:00",
            "inline": {"path": "app/settings.yaml", "from": 5},
        }
    ]
}


def bitbucket_pr(state="MERGED", draft=False):
    return {
        "id": 128,
        "title": "Add guide and rename config",
        "description": None,
        "state": state,
        "draft": draft,
        "author": {"display_name": "Alice Zhang", "nickname": "alice", "uuid": "{uuid-1}"},
        "source": {
            "branch": {"name": "feature/guide"},
            "commit": {"hash": "headsha1234567890"},
        },
        "destination": {
            "branch": {"name": "main"},
            "commit": {"hash": "basesha0987654321"},
        },
        "links": {"html": {"href": BITBUCKET_WEB_URL}},
        "created_on": "2026-01-01T00:00:00+00:00",
        "updated_on": "2026-01-04T00:00:00+00:00",
        "closed_on": "2026-01-05T00:00:00+00:00",
        "comment_count": 3,
    }


def next_page_route(first, second):
    def route(url, params):
        return second if "page=2" in url else first

    return route


def bitbucket_provider(diff_text=None, pr=None):
    fake = FakeHttp()
    fake.add(BITBUCKET_PR_URL, pr if pr is not None else bitbucket_pr())
    fake.add(f"{BITBUCKET_PR_URL}/diff", BITBUCKET_DIFF if diff_text is None else diff_text)
    fake.add_prefix(
        f"{BITBUCKET_PR_URL}/commits",
        next_page_route(BITBUCKET_COMMITS_PAGE_1, BITBUCKET_COMMITS_PAGE_2),
    )
    fake.add_prefix(
        f"{BITBUCKET_PR_URL}/comments",
        next_page_route(BITBUCKET_COMMENTS_PAGE_1, BITBUCKET_COMMENTS_PAGE_2),
    )
    ref = Ref(
        raw=BITBUCKET_WEB_URL,
        platform="bitbucket",
        host="bitbucket.org",
        project="acme/shop",
        number="128",
        url=BITBUCKET_WEB_URL,
    )
    provider = BitbucketProvider(ref, token=TOKEN)
    provider.api = fake
    return provider, fake


# --------------------------------------------------------------------------- parse_ref


class ParseRefTest(unittest.TestCase):
    """覆盖 parse_ref 对各类平台链接、简写引用和缺失参数的解析行为。"""

    def test_gitlab_urls(self):
        modern = parse_ref("https://gitlab.example.com/acme/shop/-/merge_requests/128")
        legacy = parse_ref("https://gitlab.example.com/acme/shop/merge_requests/7")
        for ref, url, number in (
            (modern, "https://gitlab.example.com/acme/shop/-/merge_requests/128", "128"),
            (legacy, "https://gitlab.example.com/acme/shop/merge_requests/7", "7"),
        ):
            with self.subTest(url=url):
                self.assertEqual(ref.platform, "gitlab")
                self.assertEqual(ref.host, "gitlab.example.com")
                self.assertEqual(ref.project, "acme/shop")
                self.assertEqual(ref.number, number)
                self.assertEqual(ref.url, url)

    def test_github_urls(self):
        public = parse_ref("https://github.com/acme/shop/pull/128")
        enterprise = parse_ref("https://github.example.com/acme/shop/pull/128")
        for ref, host in ((public, "github.com"), (enterprise, "github.example.com")):
            with self.subTest(host=host):
                self.assertEqual(ref.platform, "github")
                self.assertEqual(ref.host, host)
                self.assertEqual(ref.project, "acme/shop")
                self.assertEqual(ref.number, "128")
                self.assertEqual(ref.url, f"https://{host}/acme/shop/pull/128")

    def test_gitee_url(self):
        ref = parse_ref("https://gitee.com/acme/shop/pulls/128")
        self.assertEqual(ref.platform, "gitee")
        self.assertEqual(ref.host, "gitee.com")
        self.assertEqual(ref.project, "acme/shop")
        self.assertEqual(ref.number, "128")
        self.assertEqual(ref.url, GITEE_WEB_URL)

    def test_bitbucket_url(self):
        ref = parse_ref("https://bitbucket.org/acme/shop/pull-requests/128")
        self.assertEqual(ref.platform, "bitbucket")
        self.assertEqual(ref.host, "bitbucket.org")
        self.assertEqual(ref.project, "acme/shop")
        self.assertEqual(ref.number, "128")
        self.assertEqual(ref.url, BITBUCKET_WEB_URL)

    def test_diff_url_is_generic(self):
        url = "https://gitlab.example.com/acme/shop/-/merge_requests/128.diff"
        ref = parse_ref(url)
        self.assertEqual(ref.platform, "generic")
        self.assertEqual(ref.host, "gitlab.example.com")
        self.assertEqual(ref.number, "")
        self.assertTrue(ref.url.endswith(".diff"))
        self.assertEqual(ref.url, url)

    def test_shorthand_references(self):
        gitlab = parse_ref("acme/shop!128", host="gitlab.example.com")
        github = parse_ref("owner/repo#128", host="github.com")
        self.assertEqual(gitlab.platform, "gitlab")
        self.assertEqual(gitlab.project, "acme/shop")
        self.assertEqual(gitlab.number, "128")
        self.assertEqual(gitlab.url, "https://gitlab.example.com/acme/shop/-/merge_requests/128")
        self.assertEqual(github.platform, "github")
        self.assertEqual(github.project, "owner/repo")
        self.assertEqual(github.number, "128")
        self.assertEqual(github.url, "https://github.com/owner/repo/pull/128")

    def test_bare_number_with_project(self):
        ref = parse_ref(
            "128",
            platform="gitlab",
            project="acme/shop",
            host="gitlab.example.com",
        )
        self.assertEqual(ref.platform, "gitlab")
        self.assertEqual(ref.host, "gitlab.example.com")
        self.assertEqual(ref.project, "acme/shop")
        self.assertEqual(ref.number, "128")
        self.assertEqual(ref.url, "https://gitlab.example.com/acme/shop/-/merge_requests/128")

    def test_shorthand_without_host_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for raw in ("acme/shop!128", "owner/repo#128"):
                with self.subTest(raw=raw):
                    with self.assertRaises(FetchError):
                        parse_ref(raw)

    def test_bare_number_without_project_raises(self):
        with self.assertRaises(FetchError):
            parse_ref("128", platform="gitlab", host="gitlab.example.com")


# --------------------------------------------------------------------------- GitHub provider


class GitHubProviderTest(unittest.TestCase):
    """覆盖 GitHub provider 的状态映射、文件标记、提交、评论和失败降级。"""

    def test_state_mapping(self):
        cases = (
            ("open", None, "opened"),
            ("closed", None, "closed"),
            ("closed", "2026-10-03T00:00:00Z", "merged"),
        )
        for raw, merged_at, expected in cases:
            with self.subTest(state=raw, merged_at=merged_at):
                snapshot = github_provider(
                    github_fake(pull=github_pull(state=raw, merged_at=merged_at))
                ).fetch()
                self.assertEqual(snapshot.state, expected)

    def test_pull_metadata_and_conflicts(self):
        snapshot = github_provider().fetch()
        self.assertEqual(snapshot.platform, "github")
        self.assertEqual(snapshot.number, "128")
        self.assertEqual(snapshot.title, "Add checkout flow")
        self.assertEqual(snapshot.description, "Wire the cart to the new checkout page.")
        self.assertFalse(snapshot.draft)
        self.assertEqual(snapshot.author_username, "alice")
        self.assertEqual(snapshot.author_name, "alice")
        self.assertEqual(snapshot.source_branch, "feature/checkout")
        self.assertEqual(snapshot.target_branch, "main")
        self.assertEqual(snapshot.sha, "headsha0123456789")
        self.assertEqual(snapshot.base_sha, "basesha0123456789")
        self.assertEqual(snapshot.web_url, GITHUB_WEB_URL)
        self.assertEqual(snapshot.created_at, "2026-10-01T10:00:00Z")
        self.assertEqual(snapshot.updated_at, "2026-10-02T10:00:00Z")
        self.assertEqual(snapshot.labels, ["feature", "checkout"])
        self.assertEqual(snapshot.notes_count, 7)
        self.assertFalse(snapshot.has_conflicts)

        payload = github_pull()
        payload["mergeable"] = False
        self.assertTrue(github_provider(github_fake(pull=payload)).fetch().has_conflicts)
        payload["mergeable"] = None
        self.assertFalse(github_provider(github_fake(pull=payload)).fetch().has_conflicts)

    def test_enterprise_api_base_and_headers(self):
        ref = Ref(
            raw="",
            platform="github",
            host="github.example.com",
            project=GITHUB_PROJECT,
            number="7",
        )
        provider = GitHubProvider(ref, token=TOKEN)
        self.assertEqual(provider.base, "https://github.example.com/api/v3")
        self.assertEqual(provider.api.headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(provider.api.headers["Accept"], "application/vnd.github+json")
        self.assertEqual(provider.api.headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertEqual(github_provider().base, "https://api.github.com")

    def test_files_flags_and_patch_fallback(self):
        snapshot = github_provider().fetch()
        self.assertEqual(
            [change.new_path for change in snapshot.changes],
            ["src/checkout.py", "src/new_name.py", "src/legacy.py", "assets/logo.png"],
        )
        by_path = {change.new_path: change for change in snapshot.changes}

        added = by_path["src/checkout.py"]
        self.assertTrue(added.new_file)
        self.assertFalse(added.deleted_file)
        self.assertFalse(added.renamed_file)
        self.assertEqual(added.old_path, "src/checkout.py")
        self.assertTrue(added.diff.startswith("@@ -0,0 +1,2 @@"))
        self.assertFalse(added.too_large)

        renamed = by_path["src/new_name.py"]
        self.assertTrue(renamed.renamed_file)
        self.assertFalse(renamed.new_file)
        self.assertFalse(renamed.deleted_file)
        self.assertEqual(renamed.old_path, "src/old_name.py")
        self.assertEqual(renamed.new_path, "src/new_name.py")
        self.assertEqual(renamed.diff, "@@ -1 +1 @@\n-old\n+new")

        removed = by_path["src/legacy.py"]
        self.assertTrue(removed.deleted_file)
        self.assertFalse(removed.new_file)
        self.assertFalse(removed.renamed_file)
        self.assertEqual(removed.old_path, "src/legacy.py")
        self.assertTrue(removed.diff.startswith("@@ -1,1 +0,0 @@"))

        binary = by_path["assets/logo.png"]
        self.assertEqual(binary.diff, "")
        self.assertTrue(binary.too_large)
        self.assertTrue(binary.as_dict()["too_large"])

    def test_commits_short_id_and_title(self):
        snapshot = github_provider().fetch()
        self.assertEqual(len(snapshot.commits), 1)
        commit = snapshot.commits[0]
        self.assertEqual(commit.short_id, "0123456")
        self.assertEqual(commit.title, "feat: add checkout page")
        self.assertEqual(commit.message, "feat: add checkout page\n\nWire the cart to checkout.")
        self.assertEqual(commit.author_name, "Alice Zhang")
        self.assertEqual(commit.created_at, "2026-10-01T11:00:00Z")

    def test_discussions_group_and_locations(self):
        snapshot = github_provider().fetch()
        self.assertEqual(
            [discussion.id for discussion in snapshot.discussions],
            ["review-501", "review-502", "issue-900"],
        )
        self.assertTrue(all(len(discussion.notes) == 1 for discussion in snapshot.discussions))

        first = snapshot.discussions[0].notes[0]
        self.assertEqual(first.id, "501")
        self.assertEqual(first.author, "reviewer1")
        self.assertEqual(first.body, "Rename this helper.")
        self.assertEqual(first.created_at, "2026-10-01T12:00:00Z")
        self.assertEqual(first.file, "src/checkout.py")
        self.assertEqual(first.line, 12)
        self.assertTrue(first.resolvable)
        self.assertFalse(first.resolved)

        fallback = snapshot.discussions[1].notes[0]
        self.assertEqual(fallback.line, 7)
        self.assertEqual(fallback.file, "src/legacy.py")

        issue = snapshot.discussions[2].notes[0]
        self.assertEqual(issue.id, "900")
        self.assertEqual(issue.author, "alice")
        self.assertEqual(issue.file, "")
        self.assertIsNone(issue.line)
        self.assertFalse(issue.resolvable)

    def test_comment_endpoint_failures_degrade_to_notes(self):
        snapshot = github_provider(
            github_fake(fail=(GITHUB_REVIEWS_URL, GITHUB_ISSUE_COMMENTS_URL))
        ).fetch()
        self.assertEqual(snapshot.discussions, [])
        self.assertEqual(
            snapshot.notes,
            [
                "review comments 需要 repo 读权限，已跳过",
                "issue comments 需要 repo 读权限，已跳过",
            ],
        )

        partial = github_provider(github_fake(fail=(GITHUB_ISSUE_COMMENTS_URL,))).fetch()
        self.assertEqual(
            [discussion.id for discussion in partial.discussions],
            ["review-501", "review-502"],
        )
        self.assertEqual(partial.notes, ["issue comments 需要 repo 读权限，已跳过"])

    def test_missing_fields_do_not_raise(self):
        snapshot = github_provider(github_fake(pull={"number": 128})).fetch()
        self.assertEqual(snapshot.title, "")
        self.assertEqual(snapshot.description, "")
        self.assertEqual(snapshot.state, "")
        self.assertEqual(snapshot.author_username, "")
        self.assertEqual(snapshot.author_name, "")
        self.assertEqual(snapshot.source_branch, "")
        self.assertEqual(snapshot.target_branch, "")
        self.assertEqual(snapshot.sha, "")
        self.assertEqual(snapshot.base_sha, "")
        self.assertEqual(snapshot.web_url, GITHUB_WEB_URL)
        self.assertEqual(snapshot.labels, [])
        self.assertEqual(snapshot.notes_count, 0)
        self.assertFalse(snapshot.has_conflicts)


# --------------------------------------------------------------------------- Gitee provider


class GiteeProviderTest(unittest.TestCase):
    """覆盖 Gitee provider 的状态映射、分页文件、提交、评论和缺字段容错。"""

    def test_state_mapping(self):
        expected = {
            "merged": "merged",
            "open": "opened",
            "opened": "opened",
            "closed": "closed",
            "progressing": "closed",
            "rejected": "closed",
        }
        for raw, want in expected.items():
            with self.subTest(state=raw):
                snapshot = gitee_provider(pull=gitee_pull(state=raw)).fetch()
                self.assertEqual(snapshot.state, want)

    def test_pull_metadata(self):
        snapshot = gitee_provider().fetch()
        self.assertEqual(snapshot.platform, "gitee")
        self.assertEqual(snapshot.number, "128")
        self.assertEqual(snapshot.title, "Add checkout page")
        self.assertEqual(snapshot.description, "Split checkout into two steps")
        self.assertEqual(snapshot.author_username, "alice")
        self.assertEqual(snapshot.author_name, "Alice Zhang")
        self.assertEqual(snapshot.source_branch, "feature/checkout")
        self.assertEqual(snapshot.target_branch, "master")
        self.assertEqual(snapshot.sha, GITEE_HEAD_SHA)
        self.assertEqual(snapshot.base_sha, GITEE_BASE_SHA)
        self.assertEqual(snapshot.web_url, GITEE_WEB_URL)
        self.assertEqual(snapshot.created_at, "2026-10-01T10:00:00+08:00")
        self.assertEqual(snapshot.updated_at, "2026-10-02T11:00:00+08:00")
        self.assertEqual(snapshot.merged_at, "")
        self.assertEqual(snapshot.labels, ["enhancement", "backend"])
        self.assertEqual(snapshot.notes_count, 7)

    def test_files_pagination_and_flags(self):
        pages = [
            [
                {
                    "filename": "app/services/checkout.rb",
                    "previous_filename": "app/services/order.rb",
                    "status": "renamed",
                    "patch": "@@ -1 +1 @@\n-old\n+new",
                },
                {
                    "filename": "README.md",
                    "status": "removed",
                    "patch": "@@ -1 +0,0 @@\n-x",
                },
            ],
            [
                {
                    "filename": "docs/new.md",
                    "status": "added",
                    "diff": "@@ -0,0 +1 @@\n+hello",
                },
                {
                    "filename": "assets/logo.png",
                    "status": "modified",
                },
            ],
            [],
        ]
        provider = gitee_provider(files=pages, per_page=2)
        snapshot = provider.fetch()
        self.assertEqual(len(snapshot.changes), 4)
        pages_called = [
            params["page"]
            for method, url, params in provider.api.calls
            if method == "json" and url == GITEE_API + GITEE_FILES_PATH
        ]
        self.assertEqual(pages_called, [1, 2, 3])

        renamed, removed, added, binary = snapshot.changes
        self.assertEqual(renamed.old_path, "app/services/order.rb")
        self.assertEqual(renamed.new_path, "app/services/checkout.rb")
        self.assertTrue(renamed.renamed_file)
        self.assertFalse(renamed.new_file)
        self.assertFalse(renamed.too_large)
        self.assertTrue(removed.deleted_file)
        self.assertTrue(added.new_file)
        self.assertEqual(added.diff, "@@ -0,0 +1 @@\n+hello")
        self.assertEqual(binary.diff, "")
        self.assertTrue(binary.too_large)
        self.assertTrue(binary.as_dict()["too_large"])

    def test_commits(self):
        pages = [
            [
                {
                    "sha": "1234567890abcdef1234567890abcdef12345678",
                    "commit": {
                        "message": "feat: add wallet payment\n\nDetails\n",
                        "author": {
                            "name": "Alice Zhang",
                            "date": "2026-10-01T09:00:00+08:00",
                        },
                    },
                },
                {
                    "sha": "abcdef1234567890abcdef1234567890abcdef12",
                    "commit": {
                        "message": "fix: handle empty input",
                        "author": {"name": "Bob Li"},
                    },
                },
            ],
            [{"sha": "9999999999", "commit": {"message": ""}}],
        ]
        snapshot = gitee_provider(commits=pages, per_page=2).fetch()
        self.assertEqual(len(snapshot.commits), 3)
        first = snapshot.commits[0]
        self.assertEqual(first.short_id, "1234567")
        self.assertEqual(first.title, "feat: add wallet payment")
        self.assertIn("Details", first.message)
        self.assertEqual(first.author_name, "Alice Zhang")
        self.assertEqual(first.created_at, "2026-10-01T09:00:00+08:00")
        third = snapshot.commits[2]
        self.assertEqual(third.short_id, "9999999")
        self.assertEqual(third.title, "")
        self.assertEqual(third.author_name, "")

    def test_review_and_issue_comments(self):
        review = [
            [
                {
                    "id": 9001,
                    "user": {"login": "reviewer1"},
                    "body": " check null ",
                    "created_at": "2026-10-02T09:00:00+08:00",
                    "path": "app/services/checkout.rb",
                    "position": 42,
                },
                {
                    "id": 9002,
                    "user": {"login": "reviewer2"},
                    "body": "line fallback",
                    "created_at": "2026-10-02T10:00:00+08:00",
                    "path": "app/services/order.rb",
                    "line": 7,
                },
            ]
        ]
        issue = [
            [
                {
                    "id": 7001,
                    "user": {"login": "pm"},
                    "body": "When will this ship?",
                    "created_at": "2026-10-02T11:00:00+08:00",
                },
                {
                    "id": 7002,
                    "user": {"login": "pm2"},
                    "body": "LGTM",
                    "created_at": "2026-10-02T12:00:00+08:00",
                },
            ]
        ]
        snapshot = gitee_provider(review=review, issue=issue).fetch()
        by_id = {discussion.id: discussion for discussion in snapshot.discussions}
        self.assertEqual(len(by_id), 4)

        first = by_id["review-9001"].notes[0]
        self.assertEqual(first.author, "reviewer1")
        self.assertEqual(first.body, "check null")
        self.assertEqual(first.file, "app/services/checkout.rb")
        self.assertEqual(first.line, 42)
        self.assertEqual(first.created_at, "2026-10-02T09:00:00+08:00")

        second = by_id["review-9002"].notes[0]
        self.assertEqual(second.line, 7)
        self.assertIsInstance(second.line, int)

        issue_note = by_id["issue-7001"].notes[0]
        self.assertEqual(issue_note.author, "pm")
        self.assertEqual(issue_note.file, "")
        self.assertIsNone(issue_note.line)

    def test_missing_fields_do_not_raise(self):
        snapshot = gitee_provider(pull={"title": "Only a title"}).fetch()
        self.assertEqual(snapshot.title, "Only a title")
        self.assertEqual(snapshot.description, "")
        self.assertEqual(snapshot.author_username, "")
        self.assertEqual(snapshot.author_name, "")
        self.assertEqual(snapshot.source_branch, "")
        self.assertEqual(snapshot.sha, "")
        self.assertEqual(snapshot.web_url, GITEE_WEB_URL)
        self.assertEqual(snapshot.labels, [])
        self.assertEqual(snapshot.notes_count, 0)
        self.assertEqual(snapshot.state, "")

        fallback = gitee_provider(
            pull=gitee_pull(body=None, user={"login": "bob"}, html_url=None)
        ).fetch()
        self.assertEqual(fallback.description, "")
        self.assertEqual(fallback.author_name, "bob")
        self.assertEqual(fallback.web_url, GITEE_WEB_URL)

    def test_endpoint_failures_degrade_to_notes(self):
        fake = gitee_fake(
            errors={GITEE_REVIEW_PATH: FetchError("GET comments -> HTTP 403")},
            issue=[[{"id": 7001, "user": {"login": "pm"}, "body": "ok"}]],
        )
        snapshot = gitee_provider(fake=fake).fetch()
        self.assertEqual(
            [discussion.id for discussion in snapshot.discussions],
            ["issue-7001"],
        )
        self.assertTrue(any("行内评论" in note for note in snapshot.notes), snapshot.notes)

        files_fake = gitee_fake(errors={GITEE_FILES_PATH: FetchError("GET files -> HTTP 403")})
        files_snapshot = gitee_provider(fake=files_fake).fetch()
        self.assertEqual(files_snapshot.changes, [])
        self.assertTrue(
            any("变更文件列表" in note for note in files_snapshot.notes),
            files_snapshot.notes,
        )

        issue_fake = gitee_fake(errors={GITEE_ISSUE_PATH: FetchError("GET issues -> HTTP 500")})
        issue_snapshot = gitee_provider(fake=issue_fake).fetch()
        self.assertEqual(issue_snapshot.discussions, [])
        self.assertTrue(any("Issue 评论" in note for note in issue_snapshot.notes), issue_snapshot.notes)


# --------------------------------------------------------------------------- Bitbucket provider


class BitbucketProviderTest(unittest.TestCase):
    """覆盖 Bitbucket provider 的 diff 切分、状态映射、分页和评论过滤。"""

    def test_fetch_splits_diff_and_collects_pages(self):
        provider, fake = bitbucket_provider()
        snapshot = provider.fetch()

        self.assertEqual(snapshot.platform, "bitbucket")
        self.assertEqual(snapshot.host, "bitbucket.org")
        self.assertEqual(snapshot.project, "acme/shop")
        self.assertEqual(snapshot.number, "128")
        self.assertEqual(snapshot.title, "Add guide and rename config")
        self.assertEqual(snapshot.description, "")
        self.assertEqual(snapshot.state, "merged")
        self.assertEqual(snapshot.merged_at, "2026-01-05T00:00:00+00:00")
        self.assertEqual(snapshot.author_name, "Alice Zhang")
        self.assertEqual(snapshot.author_username, "alice")
        self.assertEqual(snapshot.source_branch, "feature/guide")
        self.assertEqual(snapshot.target_branch, "main")
        self.assertEqual(snapshot.sha, "headsha1234567890")
        self.assertEqual(snapshot.base_sha, "basesha0987654321")
        self.assertEqual(snapshot.web_url, BITBUCKET_WEB_URL)
        self.assertEqual(snapshot.created_at, "2026-01-01T00:00:00+00:00")
        self.assertEqual(snapshot.updated_at, "2026-01-04T00:00:00+00:00")
        self.assertEqual(snapshot.notes_count, 3)
        self.assertEqual(snapshot.notes, [])

        self.assertEqual(len(snapshot.changes), 4)
        guide, main_py, legacy, renamed = snapshot.changes

        self.assertEqual((guide.old_path, guide.new_path), ("docs/guide.md", "docs/guide.md"))
        self.assertTrue(guide.new_file)
        self.assertFalse(guide.deleted_file)
        self.assertFalse(guide.renamed_file)
        self.assertEqual(guide.diff, "@@ -0,0 +1,2 @@\n+# Guide\n+hello\n")
        self.assertEqual((guide.additions, guide.deletions), (2, 0))

        self.assertEqual((main_py.old_path, main_py.new_path), ("app/main.py", "app/main.py"))
        self.assertFalse(main_py.new_file)
        self.assertFalse(main_py.deleted_file)
        self.assertFalse(main_py.renamed_file)
        self.assertEqual(
            main_py.diff,
            "@@ -1,3 +1,4 @@\n"
            " import os\n"
            '-print("old")\n'
            '+print("new")\n'
            '+print("extra")\n'
            " def main():\n",
        )
        self.assertEqual((main_py.additions, main_py.deletions), (2, 1))

        self.assertTrue(legacy.deleted_file)
        self.assertFalse(legacy.new_file)
        self.assertFalse(legacy.renamed_file)
        self.assertEqual(legacy.path, "legacy/old_module.py")
        self.assertEqual(legacy.diff, '@@ -1,2 +0,0 @@\n-print("legacy")\n-pass\n')
        self.assertEqual((legacy.additions, legacy.deletions), (0, 2))

        self.assertTrue(renamed.renamed_file)
        self.assertFalse(renamed.new_file)
        self.assertFalse(renamed.deleted_file)
        self.assertEqual(renamed.old_path, "app/config.yaml")
        self.assertEqual(renamed.new_path, "app/settings.yaml")
        self.assertEqual(renamed.path, "app/settings.yaml")
        self.assertEqual(renamed.diff, "@@ -1,1 +1,1 @@\n-name: shop\n+name: shop-renamed\n")
        self.assertEqual((renamed.additions, renamed.deletions), (1, 1))

        for change in snapshot.changes:
            self.assertNotIn("diff --git", change.diff)
            self.assertNotIn("--- a/", change.diff)
            self.assertNotIn("+++ b/", change.diff)
            self.assertNotIn("rename from", change.diff)

        self.assertEqual(
            snapshot.stats,
            {"files": 4, "additions": 5, "deletions": 4, "commits": 2},
        )

        self.assertEqual([commit.short_id for commit in snapshot.commits], ["abcdef1", "1234567"])
        self.assertEqual(snapshot.commits[0].title, "feat: add guide")
        self.assertEqual(snapshot.commits[0].message, "feat: add guide\n\nmore detail")
        self.assertEqual(snapshot.commits[0].author_name, "Alice Zhang")
        self.assertEqual(snapshot.commits[0].created_at, "2026-01-02T03:04:05+00:00")
        self.assertEqual(snapshot.commits[1].title, "fix: rename config")
        self.assertEqual(snapshot.commits[1].author_name, "Bob Li")

        self.assertEqual(
            [discussion.id for discussion in snapshot.discussions],
            ["comment-1001", "comment-1003"],
        )
        first = snapshot.discussions[0].notes[0]
        self.assertEqual(first.id, "1001")
        self.assertEqual(first.author, "Carol")
        self.assertEqual(first.body, "Looks good")
        self.assertEqual(first.created_at, "2026-01-06T00:00:00+00:00")
        self.assertEqual(first.file, "app/main.py")
        self.assertEqual(first.line, 12)
        second = snapshot.discussions[1].notes[0]
        self.assertEqual(second.body, "This can be improved")
        self.assertEqual(second.file, "app/settings.yaml")
        self.assertEqual(second.line, 5)
        self.assertEqual(len(snapshot.discussions[1].notes), 1)

        self.assertEqual(
            fake.urls(),
            [
                BITBUCKET_PR_URL,
                f"{BITBUCKET_PR_URL}/diff",
                f"{BITBUCKET_PR_URL}/commits",
                f"{BITBUCKET_PR_URL}/commits?page=2",
                f"{BITBUCKET_PR_URL}/comments",
                f"{BITBUCKET_PR_URL}/comments?page=2",
            ],
        )

    def test_state_mapping_and_merged_at(self):
        cases = {
            "OPEN": ("opened", ""),
            "MERGED": ("merged", "2026-01-05T00:00:00+00:00"),
            "DECLINED": ("closed", ""),
            "SUPERSEDED": ("closed", ""),
        }
        for raw, (expected_state, expected_merged_at) in cases.items():
            with self.subTest(state=raw):
                provider, _ = bitbucket_provider(pr=bitbucket_pr(state=raw))
                snapshot = provider.fetch()
                self.assertEqual(snapshot.state, expected_state)
                self.assertEqual(snapshot.merged_at, expected_merged_at)

    def test_empty_diff_degrades_to_note(self):
        provider, _ = bitbucket_provider(diff_text="")
        snapshot = provider.fetch()
        self.assertEqual(snapshot.changes, [])
        self.assertEqual(snapshot.stats["files"], 0)
        self.assertEqual(
            snapshot.notes,
            ["Bitbucket diff 为空或超过返回上限，changes 可能不完整"],
        )

    def test_preamble_before_first_diff_is_ignored(self):
        provider, _ = bitbucket_provider(
            diff_text="warning: output truncated by the server\n\n" + BITBUCKET_DIFF
        )
        snapshot = provider.fetch()
        self.assertEqual(len(snapshot.changes), 4)
        self.assertEqual(snapshot.changes[0].diff, "@@ -0,0 +1,2 @@\n+# Guide\n+hello\n")
        self.assertNotIn("warning", snapshot.changes[0].diff)


# --------------------------------------------------------------------------- base helpers


class SplitUnifiedDiffTest(unittest.TestCase):
    """覆盖 split_unified_diff 的路径解析、重命名和新增删除标记。"""

    def test_plain_path_and_hunk_body(self):
        text = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 line one
-old
+new
+extra
"""
        changes = split_unified_diff(text)
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(change.old_path, "src/app.py")
        self.assertEqual(change.new_path, "src/app.py")
        self.assertEqual(
            change.diff,
            "@@ -1,2 +1,3 @@\n line one\n-old\n+new\n+extra\n",
        )
        self.assertEqual((change.additions, change.deletions), (2, 1))
        self.assertFalse(change.new_file)
        self.assertFalse(change.deleted_file)
        self.assertFalse(change.renamed_file)

    def test_quoted_path_with_spaces(self):
        text = """diff --git "a/x y.txt" "b/x y.txt"
index 1111111..2222222 100644
--- "a/x y.txt"
+++ "b/x y.txt"
@@ -1 +1 @@
-old
+new
"""
        changes = split_unified_diff(text)
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(change.old_path, "x y.txt")
        self.assertEqual(change.new_path, "x y.txt")
        self.assertEqual(change.diff, "@@ -1 +1 @@\n-old\n+new\n")

    def test_rename_from_and_to(self):
        text = """diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
index 1111111..2222222 100644
--- a/old/name.py
+++ b/new/name.py
@@ -1 +1 @@
-old
+new
"""
        changes = split_unified_diff(text)
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertTrue(change.renamed_file)
        self.assertFalse(change.new_file)
        self.assertFalse(change.deleted_file)
        self.assertEqual(change.old_path, "old/name.py")
        self.assertEqual(change.new_path, "new/name.py")
        self.assertEqual(change.diff, "@@ -1 +1 @@\n-old\n+new\n")

    def test_new_and_deleted_markers(self):
        text = """diff --git a/docs/new.md b/docs/new.md
index 0000000..1111111
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1 @@
+hello
diff --git a/docs/gone.md b/docs/gone.md
index 2222222..0000000
--- a/docs/gone.md
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""
        changes = split_unified_diff(text)
        self.assertEqual(len(changes), 2)
        added, deleted = changes
        self.assertTrue(added.new_file)
        self.assertFalse(added.deleted_file)
        self.assertEqual(added.diff, "@@ -0,0 +1 @@\n+hello\n")
        self.assertTrue(deleted.deleted_file)
        self.assertFalse(deleted.new_file)
        self.assertEqual(deleted.diff, "@@ -1 +0,0 @@\n-bye\n")


class BaseHelpersTest(unittest.TestCase):
    """覆盖 redact_url 脱敏和 Snapshot.mr_json 的平台与统计字段。"""

    def test_redact_url_masks_token_and_keeps_other_params(self):
        url = (
            "https://gitee.com/api/v5/repos/acme/shop/pulls/128"
            f"?access_token={TOKEN}&page=2&per_page=100"
        )
        redacted = redact_url(url)
        self.assertNotIn(TOKEN, redacted)
        pairs = dict(parse_qsl(urlsplit(redacted).query, keep_blank_values=True))
        self.assertEqual(pairs["access_token"], "***")
        self.assertEqual(pairs["page"], "2")
        self.assertEqual(pairs["per_page"], "100")

    def test_mr_json_platform_and_stats(self):
        snapshot = sample_snapshot()
        data = snapshot.mr_json()
        self.assertEqual(data["platform"], "gitlab")
        self.assertEqual(data["host"], "gitlab.example.com")
        self.assertEqual(data["project_path"], "acme/shop")
        self.assertEqual(data["iid"], "128")
        self.assertEqual(
            data["stats"],
            {"files": 1, "additions": 2, "deletions": 1, "commits": 1},
        )

    def test_fetch_refs_do_not_change_mr_json_shape(self):
        snapshot = sample_snapshot()
        baseline = set(snapshot.mr_json())
        self.assertNotIn("fetch_refs", snapshot.mr_json())
        snapshot.fetch_refs = ["refs/merge-requests/{n}/head"]
        data = snapshot.mr_json()
        self.assertEqual(set(data), baseline)
        self.assertNotIn("fetch_refs", data)


def sample_snapshot():
    return Snapshot(
        platform="gitlab",
        host="gitlab.example.com",
        project="acme/shop",
        number="128",
        title="Add checkout",
        author_username="alice",
        author_name="Alice Zhang",
        changes=[
            Change(
                old_path="src/app.py",
                new_path="src/app.py",
                diff="@@ -1 +1,2 @@\n-old\n+new\n+more\n",
            )
        ],
        commits=[Commit(short_id="abc1234", title="feat: add checkout")],
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
