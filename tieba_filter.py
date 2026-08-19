#!/usr/bin/env python3
"""Fetch and simplify Tieba mobile thread pages for text browsers."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser


TIEBA_HOSTS = {"tieba.baidu.com", "www.tieba.baidu.com"}
MOBILE_THREAD_URL = "https://tieba.baidu.com/mo/q---1-3-0--2/m"
CGI_URL = "file:/cgi-bin/tieba_filter.py?"

DROP_CLASSES = {
    # App promotions, popups, and dead JavaScript-only controls.
    "wake_app_tip",
    "pb_new_popup",
    "more_newspinner",
    "pb_newshare",
    "set_good_popup",
    "appPromote",
    "appBottomPromote",
    "jump_page_pop_back",
    "jump_page_pop_con",
    "jump_page_pop_common",
    "frs_sign_in_prompt",
    "frs_sign_in_prompt_img",
    "fixed_bar",
    "hongbao_page_pop_common",
    "bottom_reply",
    "client_ghost_icon",
    "footer_new",
    "pb_footer",
    # Per-post controls that w3m cannot use.
    "blue_kit_right",
    "list_item_more_operation",
    "lzl_cut_more_btn",
    "father-cut-daoliu-normal-box",
    "father-cut-daoliu-from-toutiao-box",
    "father_cut_daoliu",
}

DROP_IDS = {
    "pb_reply_postor_wrap",
    "lzl_reply_postor_wrap",
}

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

SAFE_UPSTREAM_PARAMS = ("pn", "see_lz", "r")


class FetchError(RuntimeError):
    """Raised when w3m cannot retrieve a Tieba page."""


def extract_thread_id(value: str) -> str:
    """Extract a numeric Tieba thread id from a supported URL or CGI query."""

    decoded = urllib.parse.unquote_plus(html.unescape(value)).strip()
    parsed = urllib.parse.urlsplit(decoded)

    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in TIEBA_HOSTS:
            raise ValueError("only tieba.baidu.com thread URLs are supported")

        desktop_match = re.search(r"^/p/(\d+)(?:/|$)", parsed.path)
        if desktop_match:
            return desktop_match.group(1)

        kz_match = re.search(r"(?:^|&)kz=(\d+)", parsed.query)
        if kz_match:
            return kz_match.group(1)

        raise ValueError("the Tieba URL does not contain a thread id")

    raw_match = re.search(r"(?:^|[?&])(?:kz=)?(\d{5,})(?=$|[?&])", decoded)
    if raw_match:
        return raw_match.group(1)

    raise ValueError("no Tieba thread id found")


def _safe_upstream_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    decoded = urllib.parse.unquote_plus(html.unescape(value))
    for name in SAFE_UPSTREAM_PARAMS:
        match = re.search(rf"(?:^|[?&]){name}=(\d+)(?=$|[?&])", decoded)
        if match:
            params[name] = match.group(1)
    return params


def _forum_request_params(value: str) -> tuple[str, int]:
    """Return the forum name and zero-based list offset from a list request."""

    decoded = html.unescape(value).strip()
    parsed = urllib.parse.urlsplit(decoded)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in TIEBA_HOSTS:
            raise ValueError("only tieba.baidu.com forum URLs are supported")
        query = parsed.query
    else:
        query = decoded.removeprefix("?")

    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    forum_name = params.get("kw", [""])[0].strip()
    if not forum_name:
        raise ValueError("贴吧列表地址缺少 kw 参数")

    offset_value = params.get("pn", ["0"])[0]
    if not re.fullmatch(r"\d+", offset_value):
        raise ValueError("贴吧列表 pn 参数必须是非负整数")
    return forum_name, int(offset_value)


def _is_forum_request(value: str) -> bool:
    decoded = html.unescape(value)
    parsed = urllib.parse.urlsplit(decoded)
    query = parsed.query if parsed.scheme or parsed.netloc else decoded.removeprefix("?")
    return "kw" in urllib.parse.parse_qs(query, keep_blank_values=True)


def _cgi_href_for_tieba_url(href: str, base_url: str) -> str:
    absolute = urllib.parse.urljoin(base_url, html.unescape(href))
    try:
        thread_id = extract_thread_id(absolute)
    except ValueError:
        return href

    query = urllib.parse.urlencode(_safe_upstream_params(absolute))
    return f"{CGI_URL}{thread_id}" + (f"&{query}" if query else "")


class _TiebaHTMLFilter(HTMLParser):
    def __init__(self, *, base_url: str | None, rewrite_links: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.rewrite_links = rewrite_links
        self.output: list[str] = []
        self.skip_depth = 0
        self.base_written = False

    @staticmethod
    def _attr_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name.lower(): value or "" for name, value in attrs}

    def _should_drop(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in {"script", "style"}:
            return True

        attr_map = self._attr_map(attrs)
        classes = set(attr_map.get("class", "").split())
        if classes & DROP_CLASSES or attr_map.get("id") in DROP_IDS:
            return True

        if tag == "img":
            src = attr_map.get("src", "")
            if "user_img" in classes:
                return True
            if "/editor/images/client/image_emoticon" in src:
                return True

        return False

    def _format_attrs(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> list[tuple[str, str | None]]:
        if not self.rewrite_links or not self.base_url or tag != "a":
            return attrs

        formatted: list[tuple[str, str | None]] = []
        for name, value in attrs:
            if name.lower() == "href" and value:
                value = _cgi_href_for_tieba_url(value, self.base_url)
            formatted.append((name, value))
        return formatted

    @staticmethod
    def _start_tag(tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> str:
        rendered = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                rendered.append(f" {name}")
            else:
                rendered.append(f' {name}="{html.escape(value, quote=True)}"')
        rendered.append(" />" if closed else ">")
        return "".join(rendered)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.skip_depth:
            if tag not in VOID_ELEMENTS:
                self.skip_depth += 1
            return

        if self._should_drop(tag, attrs):
            if tag not in VOID_ELEMENTS:
                self.skip_depth = 1
            return

        attrs = self._format_attrs(tag, attrs)
        self.output.append(self._start_tag(tag, attrs, False))
        if tag == "head" and self.base_url and not self.base_written:
            self.output.append(
                f'<base href="{html.escape(self.base_url, quote=True)}">'
            )
            self.base_written = True

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if self.skip_depth or self._should_drop(tag, attrs):
            return
        attrs = self._format_attrs(tag, attrs)
        self.output.append(self._start_tag(tag, attrs, True))

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        self.output.append(f"</{tag.lower()}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<?{data}>")


def filter_tieba_html(
    source: str,
    *,
    base_url: str | None = None,
    rewrite_links: bool = False,
) -> str:
    """Remove Tieba UI clutter while preserving readable post content."""

    parser = _TiebaHTMLFilter(base_url=base_url, rewrite_links=rewrite_links)
    parser.feed(source)
    parser.close()
    return "".join(parser.output)


def add_forum_pagination(source: str, request_value: str) -> str:
    """Add ordinary links for Tieba's JavaScript-only forum pagination."""

    forum_name, requested_offset = _forum_request_params(request_value)
    page_match = re.search(r"\bpage\s*:\s*(\{[^{}]+\})", source)
    page_data: dict[str, object] = {}
    if page_match:
        try:
            page_data = json.loads(page_match.group(1))
        except (json.JSONDecodeError, TypeError):
            page_data = {}

    page_size = page_data.get("page_size", 30)
    offset = page_data.get("offset", requested_offset)
    total_page = page_data.get("total_page")
    if not isinstance(page_size, int) or page_size <= 0:
        page_size = 30
    if not isinstance(offset, int) or offset < 0:
        offset = requested_offset

    current_page = offset // page_size + 1
    if isinstance(page_data.get("current_page"), int):
        current_page = int(page_data["current_page"])

    def page_href(page_offset: int) -> str:
        query = urllib.parse.urlencode({"kw": forum_name, "pn": page_offset})
        return html.escape(f"{CGI_URL}{query}", quote=True)

    links: list[str] = []
    if offset > 0:
        links.append(f'<a href="{page_href(max(0, offset - page_size))}">上一页</a>')

    if isinstance(total_page, int) and total_page > 0:
        links.append(f"第 {current_page} / {total_page} 页")
        has_next = current_page < total_page
    else:
        links.append(f"第 {current_page} 页")
        has_next = True

    if has_next:
        links.append(f'<a href="{page_href(offset + page_size)}">下一页</a>')

    pager = '<nav class="tieba_cli_pager"><hr><p>' + " | ".join(links) + "</p></nav>"
    body_end = source.lower().rfind("</body>")
    if body_end >= 0:
        return source[:body_end] + pager + source[body_end:]
    return source + pager


def _build_upstream_url(request_value: str) -> str:
    if _is_forum_request(request_value):
        forum_name, offset = _forum_request_params(request_value)
        params = {"kw": forum_name}
        if offset:
            params["pn"] = str(offset)
        return f"{MOBILE_THREAD_URL}?{urllib.parse.urlencode(params)}"

    params = {"kz": extract_thread_id(request_value)}
    params.update(_safe_upstream_params(request_value))
    return f"{MOBILE_THREAD_URL}?{urllib.parse.urlencode(params)}"


def fetch_tieba_html(request_value: str, *, timeout: float = 25.0) -> tuple[str, str]:
    """Fetch a server-rendered Tieba mobile thread or forum page."""

    upstream_url = _build_upstream_url(request_value)
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


def render_request(request_value: str) -> str:
    source, upstream_url = fetch_tieba_html(request_value)
    if _is_forum_request(request_value):
        source = add_forum_pagination(source, request_value)
    return filter_tieba_html(
        source,
        base_url=upstream_url,
        rewrite_links=True,
    )


def _error_page(message: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
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
    parser = argparse.ArgumentParser(
        description="Download and simplify a Tieba thread or forum page for w3m."
    )
    parser.add_argument(
        "url", help="Tieba /p/ URL, forum-list URL, mobile URL, or numeric thread ID"
    )
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
