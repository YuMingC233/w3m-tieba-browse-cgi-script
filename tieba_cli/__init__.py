"""Reusable components for the legacy Tieba mobile adapter."""

from .app import cgi_main, cli_main, main, render_request
from .errors import FetchError
from .exporting import export_thread
from .fetching import fetch_tieba_html
from .filtering import filter_tieba_html
from .rendering import add_forum_pagination, add_thread_pagination, render_lzl_page
from .routing import build_upstream_url, extract_thread_id

__all__ = [
    "FetchError",
    "add_forum_pagination",
    "add_thread_pagination",
    "build_upstream_url",
    "cgi_main",
    "cli_main",
    "extract_thread_id",
    "export_thread",
    "fetch_tieba_html",
    "filter_tieba_html",
    "main",
    "render_lzl_page",
    "render_request",
]
