"""Parse legacy Tieba mobile HTML and nested-reply JSON into models."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

from .constants import VOID_ELEMENTS
from .errors import FetchError
from .models import NestedReply, NestedReplyPage, Post, ThreadPage


CONTENT_DROP_CLASSES = {
    "img_desc",
    "video_daoliu",
}


def _attribute_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


def _clean_text(parts: list[str]) -> str:
    text = html.unescape("".join(parts)).replace("\xa0", " ")
    text = re.sub(r"[\t\r\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_data(source: str) -> dict[str, object]:
    match = re.search(r"\bpage\s*:\s*(\{[^{}]+\})", source)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _integer(data: dict[str, object], name: str, default: int) -> int:
    value = data.get(name)
    return value if isinstance(value, int) and value >= 0 else default


class _TextCaptureMixin:
    capture_parts: list[str] | None
    capture_depth: int

    def _capture(self, parts: list[str]) -> None:
        if self.capture_parts is None:
            self.capture_parts = parts
            self.capture_depth = 1

    def _capture_start_tag(self, tag: str) -> None:
        if self.capture_parts is None:
            return
        if tag == "br":
            self.capture_parts.append("\n")
        elif tag not in VOID_ELEMENTS:
            self.capture_depth += 1

    def _capture_end_tag(self) -> None:
        if self.capture_parts is None:
            return
        self.capture_depth -= 1
        if self.capture_depth == 0:
            self.capture_parts = None

    def handle_data(self, data: str) -> None:
        if self.capture_parts is not None:
            self.capture_parts.append(data)


class _ThreadPageParser(_TextCaptureMixin, HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.forum_parts: list[str] = []
        self.posts: list[Post] = []
        self.current_post: dict[str, object] | None = None
        self.post_li_depth = 0
        self.current_nested: dict[str, object] | None = None
        self.nested_li_depth = 0
        self.capture_parts = None
        self.capture_depth = 0
        self.capture_skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = _attribute_map(attrs)
        classes = set(attr_map.get("class", "").split())
        if self.capture_skip_depth:
            if tag not in VOID_ELEMENTS:
                self.capture_skip_depth += 1
            return
        if self.capture_parts is not None and classes & CONTENT_DROP_CLASSES:
            if tag not in VOID_ELEMENTS:
                self.capture_skip_depth = 1
            return
        self._capture_start_tag(tag)

        if tag == "li" and self.current_post is None and "post_list_item" in classes:
            data_info: dict[str, object] = {}
            try:
                candidate = json.loads(attr_map.get("data-info", "{}"))
                if isinstance(candidate, dict):
                    data_info = candidate
            except (json.JSONDecodeError, TypeError):
                pass
            floor_value = attr_map.get("fn", "")
            self.current_post = {
                "pid": attr_map.get("tid", ""),
                "floor": int(floor_value) if floor_value.isdigit() else None,
                "author": str(data_info.get("name_show", "")),
                "author_parts": [],
                "time_parts": [],
                "content_parts": [],
                "nested_reply_count": 0,
                "nested_replies": [],
            }
            self.post_li_depth = 1
        elif tag == "li" and self.current_post is not None:
            self.post_li_depth += 1
            if "list_item_floor" in classes and self.current_nested is None:
                self.current_nested = {
                    "pid": attr_map.get("pid", ""),
                    "author_parts": [],
                    "content_parts": [],
                }
                self.nested_li_depth = 1
            elif self.current_nested is not None:
                self.nested_li_depth += 1

        if tag == "title":
            self._capture(self.title_parts)
        elif "post_title_text" in classes:
            self._capture(self.forum_parts)
        elif self.current_nested is not None:
            if tag == "a" and "user_name" in classes:
                self._capture(self.current_nested["author_parts"])
            elif "floor_content" in classes:
                self._capture(self.current_nested["content_parts"])
        elif self.current_post is not None:
            if "list_item_time" in classes:
                self._capture(self.current_post["time_parts"])
            elif tag == "div" and "content" in classes:
                self._capture(self.current_post["content_parts"])
            elif (
                not self.current_post["author"]
                and "user_name" in classes
            ):
                self._capture(self.current_post["author_parts"])
            elif tag == "div" and "fr_list" in classes:
                count = attr_map.get("data-list-count", "")
                if count.isdigit():
                    self.current_post["nested_reply_count"] = int(count)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.capture_skip_depth:
            self.capture_skip_depth -= 1
            return
        self._capture_end_tag()
        if tag != "li" or self.current_post is None:
            return

        if self.current_nested is not None:
            self.nested_li_depth -= 1
            if self.nested_li_depth == 0:
                reply = NestedReply(
                    pid=str(self.current_nested["pid"]),
                    author=_clean_text(self.current_nested["author_parts"]).rstrip(":："),
                    content=_clean_text(self.current_nested["content_parts"]),
                )
                self.current_post["nested_replies"].append(reply)
                self.current_nested = None

        self.post_li_depth -= 1
        if self.post_li_depth == 0:
            author = str(self.current_post["author"]) or _clean_text(
                self.current_post["author_parts"]
            )
            self.posts.append(
                Post(
                    pid=str(self.current_post["pid"]),
                    floor=self.current_post["floor"],
                    author=author,
                    posted_at=_clean_text(self.current_post["time_parts"]),
                    content=_clean_text(self.current_post["content_parts"]),
                    nested_reply_count=int(self.current_post["nested_reply_count"]),
                    nested_replies=list(self.current_post["nested_replies"]),
                )
            )
            self.current_post = None

    def handle_data(self, data: str) -> None:
        if not self.capture_skip_depth:
            super().handle_data(data)


class _NestedReplyParser(_TextCaptureMixin, HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.replies: list[NestedReply] = []
        self.current: dict[str, object] | None = None
        self.li_depth = 0
        self.capture_parts = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._capture_start_tag(tag)
        attr_map = _attribute_map(attrs)
        classes = set(attr_map.get("class", "").split())
        if tag == "li" and self.current is None and "list_item_floor" in classes:
            self.current = {
                "pid": attr_map.get("pid", ""),
                "author_parts": [],
                "content_parts": [],
            }
            self.li_depth = 1
        elif tag == "li" and self.current is not None:
            self.li_depth += 1

        if self.current is not None:
            if tag == "a" and "user_name" in classes:
                self._capture(self.current["author_parts"])
            elif "floor_content" in classes:
                self._capture(self.current["content_parts"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        self._capture_end_tag()
        if tag != "li" or self.current is None:
            return
        self.li_depth -= 1
        if self.li_depth == 0:
            self.replies.append(
                NestedReply(
                    pid=str(self.current["pid"]),
                    author=_clean_text(self.current["author_parts"]).rstrip(":："),
                    content=_clean_text(self.current["content_parts"]),
                )
            )
            self.current = None


def parse_thread_page(source: str, thread_id: str) -> ThreadPage:
    """Parse one legacy mobile thread page."""

    parser = _ThreadPageParser()
    parser.feed(source)
    parser.close()
    page = _page_data(source)
    page_size = _integer(page, "page_size", 30) or 30
    offset = _integer(page, "offset", 0)
    current_page = _integer(page, "current_page", offset // page_size + 1)
    total_pages = _integer(page, "total_page", current_page)
    total_posts = _integer(page, "total_num", len(parser.posts))
    title = _clean_text(parser.title_parts)
    title = re.sub(r"^第\d+/\d+页,?回贴列表-", "", title)
    forum_name = _clean_text(parser.forum_parts).removesuffix("吧")
    return ThreadPage(
        thread_id=thread_id,
        title=title,
        forum_name=forum_name,
        page_size=page_size,
        offset=offset,
        current_page=current_page,
        total_pages=total_pages,
        total_posts=total_posts,
        posts=parser.posts,
    )


def parse_lzl_page(source: str) -> NestedReplyPage:
    """Parse one legacy mobile ``flr`` JSON response."""

    try:
        payload = json.loads(source)
        data = payload["data"]
        page = data["page"]
        floor_html = data["floor_html"]
        total_replies = page["total_num"]
        total_pages = page["total_page"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FetchError("贴吧楼中楼接口返回了无法识别的数据") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("no") != 0
        or not isinstance(floor_html, str)
        or not isinstance(total_replies, int)
        or not isinstance(total_pages, int)
    ):
        raise FetchError("贴吧楼中楼接口返回异常")

    parser = _NestedReplyParser()
    parser.feed(floor_html)
    parser.close()
    return NestedReplyPage(
        total_replies=total_replies,
        total_pages=total_pages,
        replies=parser.replies,
    )
