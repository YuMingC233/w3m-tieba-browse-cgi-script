"""Build a chronological Markdown document from a cached owner's posts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import FetchError
from .routing import extract_thread_id


_CHINA_TIMEZONE = timezone(timedelta(hours=8))


def _default_cache_root() -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_root) if cache_root else Path.home() / ".cache"
    return base / "tieba-cli" / "threads"


def _read_snapshot(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FetchError(f"未找到帖子缓存：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FetchError(f"无法读取帖子缓存：{path}") from exc
    if not isinstance(value, dict):
        raise FetchError(f"帖子缓存格式无效：{path}")
    return value


def _validate_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    if snapshot.get("schema_version") != 2:
        raise FetchError("只支持 schema_version 为 2 的帖子缓存")

    export = snapshot.get("export")
    if not isinstance(export, dict) or export.get("status") != "complete":
        raise FetchError("帖子缓存尚未完整导出，请先完成 export")
    if export.get("include_lzl") is not True:
        raise FetchError(
            "帖子缓存未包含完整楼中楼，请先使用 export --include-lzl"
        )

    thread = snapshot.get("thread")
    posts = snapshot.get("posts")
    if not isinstance(thread, dict) or not isinstance(posts, list):
        raise FetchError("帖子缓存缺少 thread 或 posts 数据")
    return thread, posts


def _parse_posted_at(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return float(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CHINA_TIMEZONE)
    return parsed.timestamp()


def _display_time(value: object) -> str:
    text = str(value or "").strip()
    timestamp = _parse_posted_at(text)
    if timestamp is None:
        return "时间未知"
    if re.fullmatch(r"\d+", text):
        return datetime.fromtimestamp(timestamp, _CHINA_TIMEZONE).isoformat(
            sep=" ", timespec="seconds"
        )
    return text


def _image_urls(content: object) -> list[str]:
    if not isinstance(content, list):
        return []

    urls: list[str] = []

    def add(candidate: object) -> None:
        if not isinstance(candidate, str) or not candidate.startswith(
            ("http://", "https://")
        ):
            return
        if candidate not in urls:
            urls.append(candidate)

    for item in content:
        if not isinstance(item, dict):
            continue
        add(item.get("origin_src"))
        media = item.get("media")
        if isinstance(media, list):
            for image in media:
                if not isinstance(image, dict):
                    continue
                add(image.get("origin_src"))
                add(image.get("big_cdn_src"))
                add(image.get("cdn_src"))
        attributes = item.get("attributes")
        if isinstance(attributes, dict) and (
            item.get("type") == "image" or item.get("tag") == "img"
        ):
            add(attributes.get("data-original"))
            add(attributes.get("origin_src"))
            add(attributes.get("src"))
    return urls


def _safe_metadata(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _owner_entries(posts: list[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sequence = 0
    for post in posts:
        if not isinstance(post, dict):
            continue
        if post.get("is_thread_owner") is True:
            entries.append(
                {
                    "kind": "主楼层",
                    "pid": _safe_metadata(post.get("pid")),
                    "floor": post.get("floor"),
                    "parent_pid": "",
                    "posted_at": _safe_metadata(post.get("posted_at")),
                    "content_text": str(post.get("content_text") or "").strip(),
                    "image_urls": _image_urls(post.get("content")),
                    "sequence": sequence,
                }
            )
            sequence += 1

        nested_replies = post.get("nested_replies")
        if not isinstance(nested_replies, list):
            continue
        for reply in nested_replies:
            if not isinstance(reply, dict) or reply.get("is_thread_owner") is not True:
                continue
            entries.append(
                {
                    "kind": "楼中楼",
                    "pid": _safe_metadata(reply.get("pid")),
                    "floor": post.get("floor"),
                    "parent_pid": _safe_metadata(post.get("pid")),
                    "posted_at": _safe_metadata(reply.get("posted_at")),
                    "content_text": str(reply.get("content_text") or "").strip(),
                    "image_urls": _image_urls(reply.get("content")),
                    "sequence": sequence,
                }
            )
            sequence += 1

    def sort_key(entry: dict[str, Any]) -> tuple[int, float, int]:
        timestamp = _parse_posted_at(entry["posted_at"])
        if timestamp is None:
            return 1, 0.0, int(entry["sequence"])
        return 0, timestamp, int(entry["sequence"])

    entries.sort(key=sort_key)
    return entries


def _render_markdown(
    thread: dict[str, Any], owner: dict[str, Any], entries: list[dict[str, Any]]
) -> str:
    title = _safe_metadata(thread.get("title")) or "未命名帖子"
    thread_id = _safe_metadata(thread.get("id"))
    author = _safe_metadata(owner.get("author")) or "未知楼主"
    author_id = _safe_metadata(owner.get("author_id"))
    lines = [
        f"# {author} 的发言",
        "",
        f"- 用户 ID：{author_id}",
        f"- 帖子：{title}",
        f"- 帖子 ID：{thread_id}",
        f"- 收录发言：{len(entries)} 条",
        "",
    ]

    for entry in entries:
        lines.extend(
            [
                f"## {_display_time(entry['posted_at'])}",
                "",
                f"- 类型：{entry['kind']}",
            ]
        )
        floor = entry.get("floor")
        if isinstance(floor, int):
            lines.append(f"- 所属楼层：{floor} 楼")
        if entry["pid"]:
            lines.append(f"- PID：{entry['pid']}")
        if entry["parent_pid"]:
            lines.append(f"- 父楼层 PID：{entry['parent_pid']}")
        lines.append("")
        lines.append(entry["content_text"] or "（无纯文本内容）")
        image_urls = entry["image_urls"]
        if image_urls:
            lines.extend(["", "图片："])
            for number, url in enumerate(image_urls, 1):
                lines.append(f"- [图片 {number}]({url})")
        lines.extend(["", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def export_owner_markdown(
    value: str, *, cache_root: Path | str | None = None
) -> Path:
    """Write the cached thread owner's posts to an author-id Markdown file."""

    thread_id = extract_thread_id(value)
    root = Path(cache_root) if cache_root is not None else _default_cache_root()
    thread_dir = root / thread_id
    snapshot = _read_snapshot(thread_dir / "thread.json")
    thread, posts = _validate_snapshot(snapshot)

    owner = thread.get("owner")
    if not isinstance(owner, dict) or owner.get("status") != "detected":
        raise FetchError("帖子缓存无法确认楼主身份")
    author_id = _safe_metadata(owner.get("author_id"))
    if not re.fullmatch(r"\d+", author_id) or author_id == "0":
        raise FetchError("帖子缓存没有可用的楼主用户 ID")

    entries = _owner_entries(posts)
    if not entries:
        raise FetchError("帖子缓存中没有已标记的楼主发言")

    output_path = thread_dir / f"{author_id}.md"
    temporary_path = thread_dir / f".{author_id}.md.tmp"
    try:
        temporary_path.write_text(
            _render_markdown(thread, owner, entries), encoding="utf-8"
        )
        temporary_path.replace(output_path)
    except OSError as exc:
        raise FetchError(f"无法写入楼主 Markdown：{output_path}") from exc
    return output_path


def owner_markdown_cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tieba_cli owner-md",
        description="从完整帖子缓存生成按时间排序的楼主发言 Markdown。",
    )
    parser.add_argument("thread", help="贴吧帖子 ID 或受支持的帖子 URL")
    args = parser.parse_args(argv)
    try:
        output_path = export_owner_markdown(args.thread)
    except (ValueError, OSError, FetchError) as exc:
        parser.exit(1, f"tieba-owner-md: {exc}\n")
    print(output_path)
    return 0
