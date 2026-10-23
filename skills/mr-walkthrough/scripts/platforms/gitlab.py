#!/usr/bin/env python3
"""GitLab provider (gitlab.com and self-hosted GitLab CE/EE).

API: https://docs.gitlab.com/ee/api/merge_requests.html
Auth: PRIVATE-TOKEN header (personal/project access token, or glab's token).
"""

from __future__ import annotations

import urllib.parse

from .base import Change, Commit, Discussion, Http, Note, Provider, Ref, Snapshot


class GitLabProvider(Provider):
    name = "gitlab"
    web_name = "GitLab"

    def __init__(self, ref: Ref, token: str = ""):
        super().__init__(ref, token)
        self.api = Http({"PRIVATE-TOKEN": token} if token else {})
        self.project_enc = urllib.parse.quote(ref.project, safe="")
        self.base = self.api_url("/api/v4")

    @classmethod
    def match(cls, url: str) -> bool:
        return "/-/merge_requests/" in url or "/merge_requests/" in url

    def fetch(self) -> Snapshot:
        mr = self.api.json(f"{self.base}/projects/{self.project_enc}/merge_requests/{self.ref.number}")
        changes = self._changes()
        commits = self._commits()
        discussions = self._discussions()
        pipeline = mr.get("head_pipeline") or {}
        diff_refs = mr.get("diff_refs") or {}
        author = mr.get("author") or {}

        return Snapshot(
            platform=self.name,
            host=self.ref.host,
            project=self.ref.project,
            number=str(mr.get("iid") or self.ref.number),
            title=mr.get("title", ""),
            description=mr.get("description") or "",
            state=mr.get("state", ""),
            draft=bool(mr.get("draft") or mr.get("work_in_progress")),
            author_username=author.get("username", ""),
            author_name=author.get("name", ""),
            source_branch=mr.get("source_branch", ""),
            target_branch=mr.get("target_branch", ""),
            sha=mr.get("sha") or "",
            base_sha=diff_refs.get("base_sha") or "",
            web_url=mr.get("web_url") or self.ref.url,
            created_at=mr.get("created_at") or "",
            updated_at=mr.get("updated_at") or "",
            merged_at=mr.get("merged_at") or "",
            labels=mr.get("labels") or [],
            notes_count=mr.get("user_notes_count") or 0,
            has_conflicts=bool(mr.get("has_conflicts")),
            changes=changes,
            commits=commits,
            discussions=discussions,
            pipeline={"status": pipeline.get("status", ""), "web_url": pipeline.get("web_url", "")},
            fetch_refs=["refs/merge-requests/{n}/head"],
        )

    # -- endpoints ---------------------------------------------------------

    def _changes(self) -> list[Change]:
        url = f"{self.base}/projects/{self.project_enc}/merge_requests/{self.ref.number}/changes"
        data = self.api.json(url)
        raw = data.get("changes") or []
        if data.get("overflow") or not raw:
            # Above ~200 files / 20k lines GitLab collapses `changes`; `diffs` still pages.
            url = url.replace("/changes", "/diffs")
            raw = self.api.paged(url)
        return [self._change(c) for c in raw]

    def _change(self, item: dict) -> Change:
        diff = item.get("diff") or ""
        return Change(
            old_path=item.get("old_path") or item.get("new_path") or "",
            new_path=item.get("new_path") or item.get("old_path") or "",
            diff=diff,
            new_file=bool(item.get("new_file")),
            deleted_file=bool(item.get("deleted_file")),
            renamed_file=bool(item.get("renamed_file")),
            too_large=bool(item.get("too_large")) or diff == "",
        )

    def _commits(self) -> list[Commit]:
        url = f"{self.base}/projects/{self.project_enc}/merge_requests/{self.ref.number}/commits"
        return [
            Commit(
                short_id=c.get("short_id") or "",
                title=c.get("title") or "",
                message=c.get("message") or "",
                author_name=c.get("author_name") or "",
                created_at=c.get("created_at") or "",
            )
            for c in self.api.paged(url)
        ]

    def _discussions(self) -> list[Discussion]:
        url = f"{self.base}/projects/{self.project_enc}/merge_requests/{self.ref.number}/discussions"
        out: list[Discussion] = []
        for discussion in self.api.paged(url):
            notes = [self._note(n) for n in discussion.get("notes", []) if not n.get("system")]
            if notes:
                out.append(Discussion(id=str(discussion.get("id", "")), notes=notes))
        return out

    def _note(self, note: dict) -> Note:
        position = note.get("position") or {}
        return Note(
            id=str(note.get("id", "")),
            author=(note.get("author") or {}).get("username", ""),
            body=(note.get("body") or "").strip(),
            created_at=note.get("created_at") or "",
            system=bool(note.get("system")),
            resolvable=bool(note.get("resolvable")),
            resolved=bool(note.get("resolved")),
            file=position.get("new_path") or position.get("old_path") or "",
            line=position.get("new_line") or position.get("old_line"),
        )
