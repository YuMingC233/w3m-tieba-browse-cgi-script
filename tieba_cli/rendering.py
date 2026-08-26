"""Render forum, thread, and nested-reply pages for w3m."""

from __future__ import annotations

import html
import json
import re
import urllib.parse

from collections.abc import Callable
from .constants import CGI_URL, LZL_URL
from .errors import FetchError
from .filtering import filter_tieba_html
from .routing import (
    extract_thread_id,
    forum_request_params,
    lzl_request_params,
    safe_upstream_params,
)


def add_forum_pagination(source: str, request_value: str) -> str:
    """Add ordinary links for Tieba's JavaScript-only forum pagination."""

    forum_name, requested_offset = forum_request_params(request_value)
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

    jump_form = ""
    if isinstance(total_page, int) and total_page > 0:
        form_action = html.escape(CGI_URL.removesuffix("?"), quote=True)
        jump_form = (
            f'<form action="{form_action}" method="get">'
            + '<input type="hidden" name="kw" value="'
            + html.escape(forum_name, quote=True)
            + '">'
            + f'<input type="hidden" name="page_size" value="{page_size}">'
            + f'<input type="hidden" name="total_page" value="{total_page}">'
            + '<label>跳转到第 <input type="text" inputmode="numeric" '
            + f'name="page" size="6" value="{current_page}"> 页</label> '
            + '<input type="submit" value="跳转"></form>'
        )

    pager = '<nav class="tieba_cli_pager"><hr><p>' + " | ".join(links) + "</p>"
    if jump_form:
        pager += jump_form
    pager += "</nav>"
    body_end = source.lower().rfind("</body>")
    if body_end >= 0:
        return source[:body_end] + pager + source[body_end:]
    return source + pager


def add_thread_pagination(source: str, request_value: str) -> str:
    """Add ordinary links for Tieba's JavaScript-only thread pagination."""

    thread_id = extract_thread_id(request_value)
    request_params = safe_upstream_params(request_value)
    requested_offset = int(request_params.get("pn", "0"))
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

    upstream_current_page = offset // page_size + 1
    if isinstance(page_data.get("current_page"), int):
        upstream_current_page = int(page_data["current_page"])

    reverse_order = request_params.get("r") == "1"
    total_page_known = isinstance(total_page, int) and total_page > 0
    if reverse_order and total_page_known:
        current_page = total_page - upstream_current_page + 1
    else:
        current_page = upstream_current_page

    def page_href(page_offset: int, *, reverse: bool = reverse_order) -> str:
        params = {"pn": str(page_offset)}
        if "see_lz" in request_params:
            params["see_lz"] = request_params["see_lz"]
        if reverse:
            params["r"] = "1"
        query = thread_id + "&" + urllib.parse.urlencode(params)
        return html.escape(f"{CGI_URL}{query}", quote=True)

    links: list[str] = []
    if current_page > 1:
        previous_offset = (
            offset + page_size if reverse_order else max(0, offset - page_size)
        )
        links.append(f'<a href="{page_href(previous_offset)}">上一页</a>')

    order_prefix = "倒序 · " if reverse_order else ""
    if total_page_known:
        links.append(f"{order_prefix}第 {current_page} / {total_page} 页")
        has_next = current_page < total_page
    else:
        links.append(f"{order_prefix}第 {current_page} 页")
        has_next = True

    if has_next:
        next_offset = (
            max(0, offset - page_size) if reverse_order else offset + page_size
        )
        links.append(f'<a href="{page_href(next_offset)}">下一页</a>')

    toggle_links: list[str] = []
    jump_form = ""
    if total_page_known:
        # 正序与倒序的切换
        if reverse_order:
            normal_offset = (current_page - 1) * page_size
            toggle_links.append(
                f'<a href="{page_href(normal_offset, reverse=False)}">正序查看</a>'
            )
        else:
            reverse_offset = (total_page - current_page) * page_size
            toggle_links.append(
                f'<a href="{page_href(reverse_offset, reverse=True)}">倒序查看</a>'
            )

        # 仅看楼主 / 查看全部
        only_lz = request_params.get("see_lz") == "1"
        if only_lz:
            # 关闭仅看楼主，过滤条件被改变，将强制返回第一页
            owner_href = html.escape(
                f"{CGI_URL}{thread_id}",
                quote=True
            )
            toggle_links.append(
                f'<a href="{owner_href}">查看全部</a>'
            )
        else:
            # 开启，强制返回第一页，防止越界
            owner_href = html.escape(
                f"{CGI_URL}{thread_id}&see_lz=1",
                quote=True
            )
            toggle_links.append(
                f'<a href="{owner_href}">仅看楼主</a>'
            )

        if total_page_known:
            hidden_fields = [
                f'<input type="hidden" name="kz" value="{thread_id}">',
                f'<input type="hidden" name="page_size" value="{page_size}">',
                f'<input type="hidden" name="total_page" value="{total_page}">',
            ]
            if "see_lz" in request_params:
                hidden_fields.append(
                    '<input type="hidden" name="see_lz" value="'
                    + html.escape(request_params["see_lz"], quote=True)
                    + '">'
                )
        if reverse_order:
            hidden_fields.append('<input type="hidden" name="r" value="1">')

        form_action = html.escape(CGI_URL.removesuffix("?"), quote=True)
        jump_form = (
            f'<form action="{form_action}" method="get">'
            + "".join(hidden_fields)
            + '<label>跳转到第 <input type="text" inputmode="numeric" '
            + f'name="page" size="4" value="{current_page}"> 页</label> '
            + '<input type="submit" value="跳转"></form>'
        )

    pager = '<nav class="tieba_cli_pager"><hr><p>' + " | ".join(links) + "</p>"
    if toggle_links:
        pager += "<p>" + " | ".join(toggle_links) + "</p>"

    if jump_form:
        pager += jump_form
    pager += "</nav>"

    body_end = source.lower().rfind("</body>")
    if body_end >= 0:
        return source[:body_end] + pager + source[body_end:]
    return source + pager


def _parse_lzl_payload(source: str) -> tuple[str, int, int]:
    """parse one nested-reply api response."""
    try:
        payload = json.loads(source)

        if not isinstance(payload, dict) or payload.get("no") != 0:
            raise FetchError("贴吧楼中楼接口返回异常")
        data = payload["data"]
        page_data = data["page"]

        floor_html = data["floor_html"]
        total_num = page_data["total_num"]
        total_page = page_data["total_page"]
    
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FetchError("贴吧楼中楼接口返回了无法识别的数据") from exc
    
    if (
        not isinstance(floor_html, str)
        or not isinstance(total_num, int)
        or not isinstance(total_page, int)
    ):
        raise FetchError("贴吧楼中楼接口返回异常")
    return floor_html, total_num, total_page

# !deprecated
def render_lzl_page(source: str, request_value: str) -> str:
    """Render one page of nested replies with ordinary CGI pagination links."""

    thread_id, parent_post_id, page = lzl_request_params(request_value)
    floor_html, total_num, total_page = _parse_lzl_payload(source)

    upstream_url = (
        f"{LZL_URL}?"
        + urllib.parse.urlencode(
            {"pid": parent_post_id, "kz": thread_id, "pn": 1, "fpn": page}
        )
    )
    content = filter_tieba_html(floor_html, base_url=upstream_url)

    def page_href(target_page: int) -> str:
        query = urllib.parse.urlencode(
            {
                "lzl": "1",
                "tid": thread_id,
                "pid": parent_post_id,
                "pn": target_page,
            }
        )
        return html.escape(f"{CGI_URL}{query}", quote=True)

    links: list[str] = []
    if page > 1:
        links.append(f'<a href="{page_href(page - 1)}">上一页</a>')
    links.append(f"共 {total_num} 条 · 第 {page} / {total_page} 页")
    if page < total_page:
        links.append(f'<a href="{page_href(page + 1)}">下一页</a>')

    pager = " | ".join(links)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>帖子 {thread_id} 的楼中楼</title></head><body>"
        f"<h1>楼中楼</h1><ul>{content}</ul><nav><hr><p>{pager}</p></nav>"
        "</body></html>"
    )

def render_all_lzl_page(
    request_val: str,
    fetcher: Callable[[str], tuple[str, str]],
) -> str:
    """Fetch and render every page of one nested-reply thread"""
    thread_id, parent_post_id, _ = lzl_request_params(request_val)

    def local_request(page: int) -> str:
        return urllib.parse.urlencode(
            {
                "lzl": "1",
                "tid": thread_id,
                "pid": parent_post_id,
                "pn": page,
            }
        )
    
    first_source, first_upstream_url = fetcher(local_request(1))

    # 第一页
    floor_html, total_num, total_page = _parse_lzl_payload(first_source)
    contents: list[str] = [filter_tieba_html(floor_html, base_url=first_upstream_url)]

    # 第二——n页
    for page in range(2, total_page + 1):
        source, upstream_url = fetcher(local_request(page))
        page_floor_html, _, _ = _parse_lzl_payload(source)
        contents.append(filter_tieba_html(page_floor_html, base_url=upstream_url))
    
    contents = "".join(contents)

    return (
        '<!doctype html>'
        '<html>'
        '<head>'
        '<meta charset="utf-8">'
        f'<title>帖子 {thread_id} 的楼中楼</title>'
        '</head>'
        '<body>'
        '<h1>楼中楼</h1>'
        f'<p>共 {total_num} 条</p>'
        f'<ul>{contents}</ul>'
        '</body>'
        '</html>'
    )
