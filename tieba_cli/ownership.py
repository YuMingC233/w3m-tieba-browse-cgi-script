"""Detect and apply thread-owner markers to exported Tieba posts."""

from __future__ import annotations

from typing import Any

from .models import Post


def _identity(post: Post) -> tuple[str, str, str]:
    if post.author_id and post.author_id != "0":
        return "author_id", post.author_id, post.author
    if post.author:
        return "author", post.author, post.author
    raise ValueError(f"楼层 {post.pid or post.floor} 缺少可用于标记楼主的作者")


def _matches(
    *,
    author_id: str,
    author: str,
    match_by: str,
    value: str,
) -> bool:
    return author_id == value if match_by == "author_id" else author == value


def apply_thread_owner(
    posts: list[Post], previous_posts: list[Post]
) -> dict[str, Any]:
    """Apply generated markers, preserving an override edited into thread.json."""

    previous_by_pid = {post.pid: post for post in previous_posts if post.pid}
    for post in posts:
        previous = previous_by_pid.get(post.pid)
        if previous and previous.thread_owner_override is True:
            post.thread_owner_override = True

    fresh_overrides = [
        post for post in posts if post.thread_owner_override is True
    ]
    overrides = fresh_overrides or [
        post for post in previous_posts if post.thread_owner_override is True
    ]
    unique_overrides: dict[tuple[str, str], tuple[str, str, str]] = {}
    for post in overrides:
        identity = _identity(post)
        unique_overrides[(identity[0], identity[1])] = identity
    if len(unique_overrides) > 1:
        raise ValueError("thread.json 中存在多个作者的楼主手动标记")

    if unique_overrides:
        match_by, value, author = next(iter(unique_overrides.values()))
        source = "manual_override"
    else:
        first_floor = next((post for post in posts if post.floor == 1), None)
        if first_floor is None:
            for post in posts:
                post.is_thread_owner = False
                for reply in post.nested_replies:
                    reply.is_thread_owner = False
            return {
                "status": "unknown",
                "source": "first_floor_unavailable",
                "author_id": "",
                "author": "",
                "match_by": None,
            }
        match_by, value, author = _identity(first_floor)
        source = "first_floor"

    owner_author_id = value if match_by == "author_id" else ""
    for post in posts:
        post.is_thread_owner = _matches(
            author_id=post.author_id,
            author=post.author,
            match_by=match_by,
            value=value,
        )
        for reply in post.nested_replies:
            reply.is_thread_owner = _matches(
                author_id=reply.author_id,
                author=reply.author,
                match_by=match_by,
                value=value,
            )

    return {
        "status": "detected",
        "source": source,
        "author_id": owner_author_id,
        "author": author,
        "match_by": match_by,
    }
