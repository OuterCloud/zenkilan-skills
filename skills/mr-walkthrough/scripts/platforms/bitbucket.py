#!/usr/bin/env python3
"""Bitbucket Cloud provider (bitbucket.org).

API: https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/
Auth: BITBUCKET_USERNAME + app password -> HTTP Basic, access token -> Bearer.
      With neither, requests go out unauthenticated (public repositories).
Paging: Bitbucket returns the next page as a full URL in the JSON `next` field.
Diffs: the /diff endpoint returns one text/plain unified diff for the whole PR,
       split per file by base.split_unified_diff.
"""

from __future__ import annotations

import base64
import os
import re

from .base import (
    Change,
    Commit,
    Discussion,
    FetchError,
    Http,
    Note,
    Provider,
    Ref,
    Snapshot,
    split_unified_diff,
    strip_ref_prefix,
)

PR_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?bitbucket\.org/[^/\s]+/[^/\s]+/pull-requests/\d+(?:[/?#]\S*)?$",
    re.IGNORECASE,
)

STATE_MAP = {
    "OPEN": "opened",
    "MERGED": "merged",
    "DECLINED": "closed",
    "SUPERSEDED": "closed",
}

EMPTY_DIFF_NOTE = "Bitbucket diff 为空或超过返回上限，changes 可能不完整"


def _as_line(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class BitbucketProvider(Provider):
    name = "bitbucket"
    web_name = "Bitbucket"

    def __init__(self, ref: Ref, token: str = ""):
        super().__init__(ref, token)
        self.number = strip_ref_prefix(str(ref.number))
        self.base = f"https://api.bitbucket.org/2.0/repositories/{ref.project.strip('/')}"
        self.api = Http(self._auth_headers())
        self.notes: list[str] = []

    def _auth_headers(self) -> dict[str, str]:
        username = os.environ.get("BITBUCKET_USERNAME", "").strip()
        # Basic needs both halves; a username with no token must not turn into
        # base64("user:") and silently send an empty password.
        if username and self.token:
            raw = f"{username}:{self.token}".encode("utf-8")
            return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @classmethod
    def match(cls, url: str) -> bool:
        return bool(PR_URL_RE.match((url or "").strip()))

    def fetch(self) -> Snapshot:
        self.notes = []
        pr = self.api.json(f"{self.base}/pullrequests/{self.number}")
        if not isinstance(pr, dict):
            raise FetchError(f"Bitbucket pull request {self.number} 返回的不是 JSON 对象")

        state_raw = str(pr.get("state") or "").upper()
        state = STATE_MAP.get(state_raw, state_raw.lower())
        author = pr.get("author") or {}
        source = pr.get("source") or {}
        destination = pr.get("destination") or {}
        source_commit = source.get("commit") or {}
        destination_commit = destination.get("commit") or {}
        links = pr.get("links") or {}
        html_link = links.get("html") or {}

        changes = self._changes()
        commits = self._commits()
        discussions = self._discussions()

        return Snapshot(
            platform=self.name,
            host=self.ref.host,
            project=self.ref.project,
            number=str(pr.get("id") or self.number),
            title=pr.get("title") or "",
            description=pr.get("description") or "",
            state=state,
            draft=bool(pr.get("draft")),
            author_username=author.get("nickname") or author.get("uuid") or "",
            author_name=author.get("display_name") or author.get("nickname") or "",
            source_branch=(source.get("branch") or {}).get("name") or "",
            target_branch=(destination.get("branch") or {}).get("name") or "",
            sha=source_commit.get("hash") or "",
            base_sha=destination_commit.get("hash") or "",
            web_url=html_link.get("href") or self.ref.url,
            created_at=pr.get("created_on") or "",
            updated_at=pr.get("updated_on") or "",
            merged_at=(pr.get("closed_on") or "") if state_raw == "MERGED" else "",
            notes_count=pr.get("comment_count") or 0,
            changes=changes,
            commits=commits,
            discussions=discussions,
            notes=self.notes,
        )

    # -- endpoints ---------------------------------------------------------

    def _changes(self) -> list[Change]:
        text = self.api.text(f"{self.base}/pullrequests/{self.number}/diff") or ""
        changes = split_unified_diff(text)
        if not changes:
            self.notes.append(EMPTY_DIFF_NOTE)
        return changes

    def _commits(self) -> list[Commit]:
        url = f"{self.base}/pullrequests/{self.number}/commits"
        return [self._commit(item) for item in self._paged(url)]

    def _commit(self, item: dict) -> Commit:
        message = item.get("message") or ""
        author = item.get("author") or {}
        user = author.get("user") or {}
        return Commit(
            short_id=(item.get("hash") or "")[:7],
            title=message.strip().splitlines()[0] if message.strip() else "",
            message=message,
            author_name=user.get("display_name") or "",
            created_at=item.get("date") or "",
        )

    def _discussions(self) -> list[Discussion]:
        url = f"{self.base}/pullrequests/{self.number}/comments"
        out: list[Discussion] = []
        for item in self._paged(url):
            if item.get("deleted"):
                continue
            note_id = str(item.get("id", ""))
            user = item.get("user") or {}
            content = item.get("content") or {}
            inline = item.get("inline") or {}
            line = inline.get("to")
            if line is None:
                line = inline.get("from")
            out.append(
                Discussion(
                    id=f"comment-{note_id}",
                    notes=[
                        Note(
                            id=note_id,
                            author=user.get("display_name") or "",
                            body=content.get("raw") or "",
                            created_at=item.get("created_on") or "",
                            file=inline.get("path") or "",
                            line=_as_line(line),
                        )
                    ],
                )
            )
        return out

    def _paged(self, url: str) -> list[dict]:
        """Follow the `next` full URL until Bitbucket stops returning one."""
        items: list[dict] = []
        seen: set[str] = set()
        next_url = url
        while next_url:
            if next_url in seen:
                break
            seen.add(next_url)
            data = self.api.json(next_url)
            if not isinstance(data, dict):
                raise FetchError(f"Bitbucket 分页接口返回的不是 JSON 对象: {next_url}")
            values = data.get("values") or []
            if not isinstance(values, list):
                raise FetchError(f"Bitbucket 分页接口 values 不是数组: {next_url}")
            items.extend(values)
            nxt = data.get("next")
            next_url = nxt if isinstance(nxt, str) else ""
        return items
