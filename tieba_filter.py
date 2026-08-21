#!/usr/bin/env python3
"""Compatibility entry point for the modular Tieba w3m adapter."""

from tieba_cli import (
    FetchError,
    add_forum_pagination,
    add_thread_pagination,
    build_upstream_url,
    cgi_main,
    cli_main,
    extract_thread_id,
    fetch_tieba_html,
    filter_tieba_html,
    main,
    render_lzl_page,
    render_request,
)

_build_upstream_url = build_upstream_url

__all__ = [
    "FetchError",
    "_build_upstream_url",
    "add_forum_pagination",
    "add_thread_pagination",
    "cgi_main",
    "cli_main",
    "extract_thread_id",
    "fetch_tieba_html",
    "filter_tieba_html",
    "main",
    "render_lzl_page",
    "render_request",
]


if __name__ == "__main__":
    raise SystemExit(main())
