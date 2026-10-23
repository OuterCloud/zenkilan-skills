#!/usr/bin/env python3
"""Ref parsing, provider registry and token resolution for mr_fetch.

Supported inputs (all normalized to a Ref, then handed to one provider):

    https://gitlab.example.com/acme/shop/-/merge_requests/128   GitLab (self-hosted or gitlab.com)
    https://github.com/acme/shop/pull/128                       GitHub (or GitHub Enterprise)
    https://gitee.com/acme/shop/pulls/128                       Gitee
    https://bitbucket.org/acme/shop/pull-requests/128           Bitbucket Cloud
    https://any.host/path/to/change.diff                        generic diff/patch URL
    --base-ref main --head-ref feature/x                        local two-ref comparison

Shorthand `group/project!128` (GitLab) and `owner/repo#128` (GitHub/Gitee/
Bitbucket) need a host: taken from the local origin remote, then --host, then
GITLAB_HOST. Bare `128`/`!128` additionally needs --project.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from . import bitbucket, generic, gitlab, github, gitee, local
from .base import Discussion, FetchError, Http, Note, Provider, Ref, Snapshot, strip_ref_prefix

PROVIDERS: dict[str, type[Provider]] = {
    gitlab.GitLabProvider.name: gitlab.GitLabProvider,
    github.GitHubProvider.name: github.GitHubProvider,
    gitee.GiteeProvider.name: gitee.GiteeProvider,
    bitbucket.BitbucketProvider.name: bitbucket.BitbucketProvider,
    generic.GenericProvider.name: generic.GenericProvider,
    local.LocalProvider.name: local.LocalProvider,
}

HOST_PLATFORM_HINTS = (
    ("github.com", "github"),
    ("gitee.com", "gitee"),
    ("bitbucket.org", "bitbucket"),
    ("gitlab.com", "gitlab"),
)

URL_PATTERNS = (
    # GitLab: /-/merge_requests/ is the modern form, the bare one covers old installs.
    ("gitlab", re.compile(r"^https?://(?P<host>[^/]+)/(?P<project>.+?)/-/merge_requests/(?P<num>\d+)")),
    ("gitlab", re.compile(r"^https?://(?P<host>[^/]+)/(?P<project>.+?)/merge_requests/(?P<num>\d+)")),
    # Specific hosts first so their /pulls/ path is not swallowed by the GitHub rule.
    ("gitee", re.compile(r"^https?://(?:www\.)?gitee\.com/(?P<project>[^/]+/[^/]+)/pulls?/(?P<num>\d+)")),
    ("bitbucket", re.compile(r"^https?://(?:www\.)?bitbucket\.org/(?P<project>[^/]+/[^/]+)/pull-requests/(?P<num>\d+)")),
    ("github", re.compile(r"^https?://(?P<host>[^/]+)/(?P<project>[^/]+/[^/]+)/(?:pull|pulls)/(?P<num>\d+)")),
)

SHORTHAND_RE = re.compile(r"^(?P<project>[^!\s#]+)!(?P<num>\d+)$")
SHORTHAND_HASH_RE = re.compile(r"^(?P<project>[^#\s]+)#(?P<num>\d+)$")
NUMBER_RE = re.compile(r"^[!#]?(?P<num>\d+)$")

WEB_PATHS = {
    "gitlab": "/-/merge_requests/{num}",
    "github": "/pull/{num}",
    "gitee": "/pulls/{num}",
    "bitbucket": "/pull-requests/{num}",
}

TOKEN_ENV = {
    "gitlab": ("GITLAB_TOKEN", "GL_TOKEN"),
    "github": ("GITHUB_TOKEN", "GH_TOKEN"),
    "gitee": ("GITEE_TOKEN", "GITEE_ACCESS_TOKEN"),
    "bitbucket": ("BITBUCKET_TOKEN", "BITBUCKET_ACCESS_TOKEN"),
    "generic": ("GENERIC_TOKEN", "DIFF_TOKEN"),
}

LOGIN_HINT = {
    "gitlab": "export GITLAB_TOKEN=...，或执行 glab auth login --hostname {host}",
    "github": "export GITHUB_TOKEN=...，或执行 gh auth login",
    "gitee": "export GITEE_TOKEN=...（Gitee 个人设置 → 私人令牌）",
    "bitbucket": "export BITBUCKET_TOKEN=...（Bitbucket 个人设置 → App passwords / access token）",
    "generic": "私有 diff 链接需要 token 时设置 GENERIC_TOKEN，或改用平台 API 模式",
}


# --------------------------------------------------------------------------- ref parsing


def guess_platform(host: str) -> str:
    host = (host or "").lower()
    for suffix, platform in HOST_PLATFORM_HINTS:
        if host == suffix or host.endswith("." + suffix):
            return platform
    return "gitlab"


def is_generic_url(raw: str) -> bool:
    path = urlparse(raw).path.lower()
    return path.endswith(".diff") or path.endswith(".patch")


def parse_ref(
    raw: str,
    platform: str | None = None,
    project: str | None = None,
    host: str | None = None,
    repo_host: str = "",
    repo_project: str = "",
) -> Ref:
    raw = raw.strip()
    if not raw:
        raise FetchError("MR 引用为空：传 MR/PR 的 URL，或 group/project!128、owner/repo#128、128 --project ...")

    if os.path.isfile(raw):
        suffix = Path(raw).suffix.lower()
        if suffix not in (".diff", ".patch"):
            raise FetchError(f"本地文件模式只支持 .diff / .patch，收到: {raw}")
        return Ref(raw=raw, platform="generic", host="", project=Path(raw).name, number="",
                   url=Path(raw).resolve().as_uri(), scheme="file")

    if raw.startswith(("http://", "https://")):
        if platform == "generic" or is_generic_url(raw):
            return _generic_ref(raw)
        for name, pattern in URL_PATTERNS:
            match = pattern.match(raw)
            if match:
                groups = match.groupdict()
                return Ref(
                    raw=raw,
                    platform=platform or name,
                    host=groups.get("host") or urlparse(raw).netloc,
                    project=groups["project"].strip("/"),
                    number=groups["num"],
                    url=clean_url(raw),
                )
        if platform in PROVIDERS:
            # Explicit platform, unknown URL shape: hand the URL over as-is.
            return Ref(raw=raw, platform=platform, host=urlparse(raw).netloc,
                       project=project or "", number="", url=clean_url(raw))
        raise FetchError(f"无法识别这个 MR/PR 链接: {raw!r}；可用 --platform 指定平台，或直接给 .diff/.patch 链接")

    if platform == "local":
        return Ref(raw=raw, platform="local", host="", project=repo_project, number="", url="")

    match = SHORTHAND_RE.match(raw)
    if match:
        target_platform = platform or guess_platform(host or repo_host)
        return _shorthand_ref(raw, target_platform, match.group("project"), match.group("num"),
                              host or repo_host, repo_project)

    match = SHORTHAND_HASH_RE.match(raw)
    if match:
        target_platform = platform or guess_platform(host or repo_host or "github.com")
        return _shorthand_ref(raw, target_platform, match.group("project"), match.group("num"),
                              host or repo_host, repo_project)

    match = NUMBER_RE.match(raw)
    if match:
        target_project = project or repo_project
        if not target_project:
            raise FetchError("只给了 MR 编号，但无法确定项目。请传完整 URL 或 --project group/project。")
        target_platform = platform or guess_platform(host or repo_host)
        return _shorthand_ref(raw, target_platform, target_project, match.group("num"),
                              host or repo_host, repo_project)

    raise FetchError(f"无法解析 MR 引用: {raw!r}（支持 URL / group/project!128 / owner/repo#128 / 128 --project ...）")


def _shorthand_ref(raw: str, platform: str, project: str, number: str, host: str, repo_project: str) -> Ref:
    if platform not in WEB_PATHS:
        raise FetchError(f"平台 {platform!r} 不支持简写引用，请传完整 URL")
    target_host = host or os.environ.get("GITLAB_HOST", "").strip()
    if not target_host:
        raise FetchError(
            "简写引用里没有域名：请传完整 URL，或加 --host <host>，或设置 GITLAB_HOST。"
        )
    scheme = "https"
    url = f"{scheme}://{target_host}/{project}{WEB_PATHS[platform].format(num=number)}"
    return Ref(raw=raw, platform=platform, host=target_host, project=project, number=number,
               url=url, scheme=scheme)


def _generic_ref(raw: str) -> Ref:
    parsed = urlparse(raw)
    project = re.sub(r"\.(diff|patch)$", "", parsed.path.strip("/"), flags=re.I)
    return Ref(raw=raw, platform="generic", host=parsed.netloc, project=project,
               number="", url=raw, scheme=parsed.scheme or "https")


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".split("?")[0]


# --------------------------------------------------------------------------- tokens


def resolve_token(platform: str, host: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for env in TOKEN_ENV.get(platform, ()):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    if platform == "gitlab":
        token = token_from_glab_config(host)
        if token:
            return token
    if platform == "github":
        token = token_from_gh_cli(host)
        if token:
            return token
    # No token is a valid state: public projects stay readable anonymously.
    # The CLI warns, and a 401/403 gets the login hint appended.
    return ""


def login_hint(platform: str, host: str) -> str:
    return LOGIN_HINT.get(platform, "请提供 --token 或平台环境变量").format(host=host)


def token_from_glab_config(host: str) -> str:
    """Minimal YAML scan: locate `hosts:` -> `<host>:` -> `token:`.

    Avoids a PyYAML dependency on machines that only have the stdlib.
    """
    home = Path.home()
    paths = []
    if os.environ.get("GLAB_CONFIG_DIR"):
        paths.append(Path(os.environ["GLAB_CONFIG_DIR"]) / "config.yml")
    paths += [
        home / "Library/Application Support/glab-cli/config.yml",
        home / ".config/glab-cli/config.yml",
        home / ".config/glab-cli/config.yaml",
    ]
    for path in paths:
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        in_hosts = False
        in_target = False
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if re.match(r"^hosts:\s*$", line):
                in_hosts = True
                continue
            if in_hosts and re.match(r"^\S", line):
                in_hosts = False
                in_target = False
            if in_hosts:
                match = re.match(r"^\s{2,4}([^\s:#]+):\s*$", line)
                if match:
                    in_target = match.group(1) == host
                    continue
                if in_target:
                    token = re.match(r"^\s+token:\s*(\S+)\s*$", line)
                    if token:
                        return token.group(1).strip("'\"")
    return ""


def token_from_gh_cli(host: str) -> str:
    for args in (["gh", "auth", "token", "--hostname", host or "github.com"], ["gh", "auth", "token"]):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return ""


def provider_for(ref: Ref, token: str) -> Provider:
    cls = PROVIDERS.get(ref.platform)
    if not cls:
        raise FetchError(f"不支持的平台: {ref.platform}（可选：{', '.join(sorted(PROVIDERS))}）")
    return cls(ref, token)


__all__ = [
    "Discussion",
    "FetchError",
    "Http",
    "Note",
    "Provider",
    "Ref",
    "Snapshot",
    "PROVIDERS",
    "login_hint",
    "parse_ref",
    "provider_for",
    "resolve_token",
    "strip_ref_prefix",
]
