"""Parse local requests and build legacy Tieba mobile URLs."""

from __future__ import annotations

import html
import re
import urllib.parse

from .constants import (
    LZL_URL,
    MOBILE_THREAD_URL,
    SAFE_UPSTREAM_PARAMS,
    TIEBA_HOSTS,
)


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


def safe_upstream_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    decoded = urllib.parse.unquote_plus(html.unescape(value))
    for name in SAFE_UPSTREAM_PARAMS:
        match = re.search(rf"(?:^|[?&]){name}=(\d+)(?=$|[?&])", decoded)
        if match:
            params[name] = match.group(1)
    return params


def request_query_params(value: str) -> dict[str, list[str]]:
    decoded = html.unescape(value).strip()
    parsed = urllib.parse.urlsplit(decoded)
    query = parsed.query if parsed.scheme or parsed.netloc else decoded.removeprefix("?")
    return urllib.parse.parse_qs(query, keep_blank_values=True)


def thread_jump_offset(value: str) -> int | None:
    """Convert a submitted logical thread page into Baidu's physical offset."""

    params = request_query_params(value)
    if "page" not in params:
        return None

    page_value = params.get("page", [""])[0]
    page_size_value = params.get("page_size", [""])[0]
    total_page_value = params.get("total_page", [""])[0]
    if not re.fullmatch(r"[1-9]\d*", page_value):
        raise ValueError("帖子页码必须是正整数")
    if not re.fullmatch(r"[1-9]\d*", page_size_value):
        raise ValueError("帖子分页大小无效")
    if not re.fullmatch(r"[1-9]\d*", total_page_value):
        raise ValueError("帖子总页数无效")

    page = int(page_value)
    page_size = int(page_size_value)
    total_page = int(total_page_value)
    if page > total_page:
        raise ValueError(f"帖子页码超出范围，当前共 {total_page} 页")

    reverse_order = params.get("r", ["0"])[0] == "1"
    physical_page = total_page - page if reverse_order else page - 1
    return physical_page * page_size


def forum_request_params(value: str) -> tuple[str, int]:
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

    if "page" in params:
        page_value = params.get("page", [""])[0]
        page_size_value = params.get("page_size", [""])[0]
        total_page_value = params.get("total_page", [""])[0]
        if not re.fullmatch(r"[1-9]\d*", page_value):
            raise ValueError("贴吧列表页码必须是正整数")
        if not re.fullmatch(r"[1-9]\d*", page_size_value):
            raise ValueError("贴吧列表分页大小无效")
        if not re.fullmatch(r"[1-9]\d*", total_page_value):
            raise ValueError("贴吧列表总页数无效")

        page = int(page_value)
        page_size = int(page_size_value)
        total_page = int(total_page_value)
        if page > total_page:
            raise ValueError(f"贴吧列表页码超出范围，当前共 {total_page} 页")
        return forum_name, (page - 1) * page_size

    offset_value = params.get("pn", ["0"])[0]
    if not re.fullmatch(r"\d+", offset_value):
        raise ValueError("贴吧列表 pn 参数必须是非负整数")
    return forum_name, int(offset_value)


def is_forum_request(value: str) -> bool:
    return "kw" in request_query_params(value)


def lzl_request_params(value: str) -> tuple[str, str, int]:
    """Return thread id, parent post id, and one-based nested-reply page."""

    params = request_query_params(value)
    if params.get("lzl", [""])[0] != "1":
        raise ValueError("缺少楼中楼请求标记")

    thread_id = params.get("tid", [""])[0]
    parent_post_id = params.get("pid", [""])[0]
    page_value = params.get("pn", ["1"])[0]
    if not re.fullmatch(r"\d{5,}", thread_id):
        raise ValueError("楼中楼 tid 参数无效")
    if not re.fullmatch(r"\d{5,}", parent_post_id):
        raise ValueError("楼中楼 pid 参数无效")
    if not re.fullmatch(r"[1-9]\d*", page_value):
        raise ValueError("楼中楼 pn 参数必须是正整数")
    return thread_id, parent_post_id, int(page_value)


def is_lzl_request(value: str) -> bool:
    return request_query_params(value).get("lzl") == ["1"]


def build_upstream_url(request_value: str) -> str:
    """Build an outbound URL restricted to the legacy mobile endpoints."""

    if is_lzl_request(request_value):
        thread_id, parent_post_id, page = lzl_request_params(request_value)
        return (
            f"{LZL_URL}?"
            + urllib.parse.urlencode(
                {"pid": parent_post_id, "kz": thread_id, "pn": 1, "fpn": page}
            )
        )

    if is_forum_request(request_value):
        forum_name, offset = forum_request_params(request_value)
        params = {"kw": forum_name}
        if offset:
            params["pn"] = str(offset)
        return f"{MOBILE_THREAD_URL}?{urllib.parse.urlencode(params)}"

    params = {"kz": extract_thread_id(request_value)}
    upstream_params = safe_upstream_params(request_value)
    jump_offset = thread_jump_offset(request_value)
    if jump_offset is not None:
        upstream_params["pn"] = str(jump_offset)
    for name in SAFE_UPSTREAM_PARAMS:
        if name in upstream_params:
            params[name] = upstream_params[name]
    return f"{MOBILE_THREAD_URL}?{urllib.parse.urlencode(params)}"
