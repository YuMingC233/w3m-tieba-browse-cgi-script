"""Fetch legacy Tieba mobile pages through w3m."""

from __future__ import annotations

import shutil
import subprocess

from .errors import FetchError
from .routing import build_upstream_url


def fetch_tieba_html(request_value: str, *, timeout: float = 25.0) -> tuple[str, str]:
    """Fetch a server-rendered Tieba mobile thread or forum page."""

    upstream_url = build_upstream_url(request_value)
    w3m = shutil.which("w3m")
    if not w3m:
        raise FetchError("找不到 w3m 可执行文件")

    command = [
        w3m,
        "-dump_source",
        # Reuse w3m's own cookie jar. Baidu may challenge an otherwise
        # identical anonymous request, especially through a shared proxy.
        "-cookie",
        "-o",
        "accept_encoding=identity",
        # The parent w3m redirects Tieba to this CGI. Disable siteconf in the
        # child process so fetching the upstream page cannot recurse.
        "-o",
        "siteconf_file=/dev/null",
        upstream_url,
    ]

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FetchError("贴吧页面请求超时") from exc

    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or "w3m 没有返回页面内容"
        raise FetchError(detail)

    if "<title>百度安全验证</title>" in result.stdout:
        raise FetchError("百度返回了安全验证页面，请稍后重试")

    return result.stdout, upstream_url
