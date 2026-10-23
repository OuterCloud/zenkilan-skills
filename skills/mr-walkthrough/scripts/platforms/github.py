#!/usr/bin/env python3
"""GitHub provider (github.com and GitHub Enterprise Server).

API: https://docs.github.com/en/rest/pulls/pulls
Auth: Bearer token (classic PAT, fine-grained PAT or gh CLI token).

Endpoints used:
    GET /repos/{owner}/{repo}/pulls/{number}
    GET /repos/{owner}/{repo}/pulls/{number}/files
    GET /repos/{owner}/{repo}/pulls/{number}/commits
    GET /repos/{owner}/{repo}/pulls/{number}/comments    (review comments)
    GET /repos/{owner}/{repo}/issues/{number}/comments   (conversation comments)
"""

from __future__ import annotations

import urllib.parse

from .base import Change, Commit, Discussion, FetchError, Http, Note, Provider, Ref, Snapshot


class GitHubProvider(Provider):
    name = "github"
    web_name = "GitHub"

    def __init__(self, ref: Ref, token: str = ""):
        super().__init__(ref, token)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # An empty "Authorization: Bearer" makes GitHub answer 401 instead of
        # serving the public PR, so anonymous really means no header at all.
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.api = Http(headers)
        host = (ref.host or "").lower()
        self.base = "https://api.github.com" if host == "github.com" else f"https://{ref.host}/api/v3"
        self.repo = urllib.parse.quote(ref.project, safe="/")
        self.pull_url = f"{self.base}/repos/{self.repo}/pulls/{ref.number}"
        self.notes: list[str] = []

    @classmethod
    def match(cls, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        return (
            len(parts) >= 4
            and parts[2] in ("pull", "pulls")
            and parts[3].isdigit()
        )

    def fetch(self) -> Snapshot:
        self.notes = []
        pull = self.api.json(self.pull_url)
        author = pull.get("user") or {}
        head = pull.get("head") or {}
        base = pull.get("base") or {}
        author_login = author.get("login") or ""

        return Snapshot(
            platform=self.name,
            host=self.ref.host,
            project=self.ref.project,
            number=str(pull.get("number") or self.ref.number),
            title=pull.get("title") or "",
            description=pull.get("body") or "",
            state=self._state(pull),
            draft=bool(pull.get("draft")),
            author_username=author_login,
            author_name=author.get("name") or author_login,
            source_branch=head.get("ref") or "",
            target_branch=base.get("ref") or "",
            sha=head.get("sha") or "",
            base_sha=base.get("sha") or "",
            web_url=pull.get("html_url") or self.ref.url,
            created_at=pull.get("created_at") or "",
            updated_at=pull.get("updated_at") or "",
            merged_at=pull.get("merged_at") or "",
            labels=[label.get("name") or "" for label in pull.get("labels") or [] if label.get("name")],
            notes_count=int(pull.get("comments") or 0) + int(pull.get("review_comments") or 0),
            has_conflicts=pull.get("mergeable") is False,
            changes=self._changes(),
            commits=self._commits(),
            discussions=self._discussions(),
            notes=self.notes,
        )

    # -- endpoints ---------------------------------------------------------

    def _state(self, pull: dict) -> str:
        if pull.get("merged_at"):
            return "merged"
        state = pull.get("state") or ""
        if state == "open":
            return "opened"
        if state == "closed":
            return "closed"
        return state

    def _changes(self) -> list[Change]:
        return [self._change(item) for item in self.api.paged_by_link(f"{self.pull_url}/files")]

    def _change(self, item: dict) -> Change:
        filename = item.get("filename") or ""
        old_path = item.get("previous_filename") or filename
        status = item.get("status") or ""
        patch = item.get("patch") or ""
        return Change(
            old_path=old_path,
            new_path=filename or old_path,
            diff=patch,
            new_file=status == "added",
            deleted_file=status == "removed",
            renamed_file=status == "renamed",
            too_large=patch == "",
        )

    def _commits(self) -> list[Commit]:
        out: list[Commit] = []
        for item in self.api.paged_by_link(f"{self.pull_url}/commits"):
            commit = item.get("commit") or {}
            author = commit.get("author") or {}
            sha = item.get("sha") or ""
            message = commit.get("message") or ""
            title = message.splitlines()[0].strip() if message else ""
            out.append(Commit(
                short_id=sha[:7],
                title=title,
                message=message,
                author_name=author.get("name") or "",
                created_at=author.get("date") or "",
            ))
        return out

    def _discussions(self) -> list[Discussion]:
        out: list[Discussion] = []
        try:
            for item in self.api.paged_by_link(f"{self.pull_url}/comments"):
                out.append(Discussion(id=f"review-{item.get('id', '')}", notes=[self._review_note(item)]))
        except FetchError:
            self.notes.append("review comments 需要 repo 读权限，已跳过")

        try:
            url = f"{self.base}/repos/{self.repo}/issues/{self.ref.number}/comments"
            for item in self.api.paged_by_link(url):
                out.append(Discussion(id=f"issue-{item.get('id', '')}", notes=[self._issue_note(item)]))
        except FetchError:
            self.notes.append("issue comments 需要 repo 读权限，已跳过")
        return out

    def _review_note(self, item: dict) -> Note:
        user = item.get("user") or {}
        line = item.get("line")
        if line is None:
            line = item.get("original_line")
        return Note(
            id=str(item.get("id", "")),
            author=user.get("login") or "",
            body=(item.get("body") or "").strip(),
            created_at=item.get("created_at") or "",
            resolvable=True,
            resolved=False,
            file=item.get("path") or "",
            line=line,
        )

    def _issue_note(self, item: dict) -> Note:
        user = item.get("user") or {}
        return Note(
            id=str(item.get("id", "")),
            author=user.get("login") or "",
            body=(item.get("body") or "").strip(),
            created_at=item.get("created_at") or "",
            resolvable=False,
            resolved=False,
            file="",
            line=None,
        )
