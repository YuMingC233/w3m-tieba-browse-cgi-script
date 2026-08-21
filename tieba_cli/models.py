"""Structured Tieba thread data used by exporters and agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NestedReply:
    pid: str
    author: str
    content_text: str
    content: list[dict[str, Any]] = field(default_factory=list)
    content_html: str = ""
    author_id: str = ""
    posted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Post:
    pid: str
    floor: int | None
    author: str
    posted_at: str
    content_text: str
    content: list[dict[str, Any]] = field(default_factory=list)
    content_html: str = ""
    author_id: str = ""
    nested_reply_count: int = 0
    nested_replies: list[NestedReply] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThreadPage:
    thread_id: str
    title: str
    forum_name: str
    page_size: int
    offset: int
    current_page: int
    total_pages: int
    total_posts: int
    posts: list[Post] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NestedReplyPage:
    total_replies: int
    total_pages: int
    replies: list[NestedReply] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
