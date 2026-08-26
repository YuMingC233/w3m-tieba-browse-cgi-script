"""CGI and command-line entry points for the w3m adapter."""

from __future__ import annotations

import argparse
import html
import os
import sys

from .errors import FetchError
from .fetching import fetch_tieba_html
from .filtering import filter_tieba_html
from .rendering import add_forum_pagination, add_thread_pagination, render_all_lzl_page
from .routing import is_forum_request, is_lzl_request


def render_request(request_value: str) -> str:
    if is_lzl_request(request_value):
        return render_all_lzl_page(request_value, fetch_tieba_html)
    source, upstream_url = fetch_tieba_html(request_value)
    if is_forum_request(request_value):
        source = add_forum_pagination(source, request_value)
    else:
        source = add_thread_pagination(source, request_value)
    return filter_tieba_html(
        source,
        base_url=upstream_url,
        rewrite_links=True,
    )


def _error_page(message: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>贴吧页面加载失败</title></head><body>"
        f"<h1>贴吧页面加载失败</h1><p>{html.escape(message)}</p>"
        "</body></html>"
    )


def cgi_main() -> int:
    print("Content-Type: text/html; charset=utf-8")
    print("Cache-Control: max-age=30")
    print()
    try:
        query = os.environ.get("QUERY_STRING", "")
        if not query:
            raise ValueError("缺少帖子 ID 或贴吧名称")
        print(render_request(query))
    except (ValueError, OSError, FetchError) as exc:
        print(_error_page(str(exc)))
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["export"]:
        from .exporting import export_cli_main

        return export_cli_main(arguments[1:])
    if arguments[:1] == ["owner-md"]:
        from .owner_markdown import owner_markdown_cli_main

        return owner_markdown_cli_main(arguments[1:])

    parser = argparse.ArgumentParser(
        description="Download and simplify a Tieba thread or forum page for w3m."
    )
    parser.add_argument(
        "url", help="Tieba /p/ URL, forum-list URL, mobile URL, or numeric thread ID"
    )
    args = parser.parse_args(arguments)

    try:
        sys.stdout.write(render_request(args.url))
    except (ValueError, OSError, FetchError) as exc:
        parser.exit(1, f"tieba-filter: {exc}\n")
    return 0


def main() -> int:
    if os.environ.get("GATEWAY_INTERFACE") or (
        os.environ.get("QUERY_STRING") and len(sys.argv) == 1
    ):
        return cgi_main()
    return cli_main()
