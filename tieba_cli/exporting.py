"""Resumable structured exports from the legacy Tieba mobile endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .constants import MOBILE_THREAD_URL
from .errors import FetchError
from .models import NestedReply, Post, ThreadPage
from .parsing import parse_lzl_page, parse_thread_page
from .routing import extract_thread_id


Fetcher = Callable[[str], tuple[str, str]]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    content = "".join(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        for value in values
    )
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FetchError(f"无法读取导出缓存：{path}") from exc
    if not isinstance(value, dict):
        raise FetchError(f"导出缓存格式无效：{path}")
    return value


def _post_from_dict(value: dict[str, object]) -> Post:
    nested_values = value.get("nested_replies", [])
    nested_replies = [
        NestedReply(
            pid=str(reply.get("pid", "")),
            author=str(reply.get("author", "")),
            content=str(reply.get("content", "")),
        )
        for reply in nested_values
        if isinstance(reply, dict)
    ] if isinstance(nested_values, list) else []
    floor = value.get("floor")
    return Post(
        pid=str(value.get("pid", "")),
        floor=floor if isinstance(floor, int) else None,
        author=str(value.get("author", "")),
        posted_at=str(value.get("posted_at", "")),
        content=str(value.get("content", "")),
        nested_reply_count=(
            value.get("nested_reply_count", 0)
            if isinstance(value.get("nested_reply_count", 0), int)
            else 0
        ),
        nested_replies=nested_replies,
    )


def _page_from_dict(value: dict[str, object]) -> ThreadPage:
    posts = value.get("posts", [])
    return ThreadPage(
        thread_id=str(value.get("thread_id", "")),
        title=str(value.get("title", "")),
        forum_name=str(value.get("forum_name", "")),
        page_size=int(value.get("page_size", 30)),
        offset=int(value.get("offset", 0)),
        current_page=int(value.get("current_page", 1)),
        total_pages=int(value.get("total_pages", 1)),
        total_posts=int(value.get("total_posts", 0)),
        posts=[_post_from_dict(post) for post in posts if isinstance(post, dict)]
        if isinstance(posts, list)
        else [],
    )


def _default_output_dir(thread_id: str) -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_root) if cache_root else Path.home() / ".cache"
    return base / "tieba-cli" / "threads" / thread_id


def _load_cached_pages(pages_dir: Path) -> dict[int, ThreadPage]:
    pages: dict[int, ThreadPage] = {}
    if not pages_dir.exists():
        return pages
    for path in pages_dir.glob("*.json"):
        if not path.stem.isdigit():
            continue
        page = _page_from_dict(_read_json(path))
        pages[page.offset] = page
    return pages


def _ordered_posts(pages: dict[int, ThreadPage]) -> list[Post]:
    by_pid: dict[str, Post] = {}
    without_pid: list[Post] = []
    for offset in sorted(pages):
        for post in pages[offset].posts:
            if post.pid:
                by_pid.setdefault(post.pid, post)
            else:
                without_pid.append(post)
    posts = list(by_pid.values()) + without_pid
    return sorted(
        posts,
        key=lambda post: (
            post.floor is None,
            post.floor if post.floor is not None else 0,
            post.pid,
        ),
    )


class _PacedFetcher:
    def __init__(self, fetcher: Fetcher, delay: float) -> None:
        self.fetcher = fetcher
        self.delay = delay
        self.last_request: float | None = None

    def __call__(self, request_value: str) -> tuple[str, str]:
        if self.last_request is not None and self.delay:
            remaining = self.delay - (time.monotonic() - self.last_request)
            if remaining > 0:
                time.sleep(remaining)
        result = self.fetcher(request_value)
        self.last_request = time.monotonic()
        return result


def _merge_nested_replies(post: Post, replies: list[NestedReply]) -> None:
    merged: dict[str, NestedReply] = {}
    anonymous: list[NestedReply] = []
    for reply in [*post.nested_replies, *replies]:
        if reply.pid:
            merged.setdefault(reply.pid, reply)
        elif not any(
            item.author == reply.author and item.content == reply.content
            for item in anonymous
        ):
            anonymous.append(reply)
    post.nested_replies = list(merged.values()) + anonymous


def _export_nested_replies(
    thread_id: str,
    posts: list[Post],
    export_dir: Path,
    fetch: _PacedFetcher,
    manifest: dict[str, object],
) -> None:
    lzl_dir = export_dir / "lzl"
    completed = manifest.setdefault("completed_lzl_pids", [])
    if not isinstance(completed, list):
        raise FetchError("导出清单中的楼中楼进度无效")

    for post in posts:
        if not post.pid or post.nested_reply_count <= len(post.nested_replies):
            continue

        post_dir = lzl_dir / post.pid
        cached_pages: dict[int, dict[str, object]] = {}
        if post_dir.exists():
            for path in post_dir.glob("*.json"):
                if path.stem.isdigit():
                    cached_pages[int(path.stem)] = _read_json(path)

        first = cached_pages.get(1)
        if first is None:
            source, _ = fetch(f"lzl=1&tid={thread_id}&pid={post.pid}&pn=1")
            parsed = parse_lzl_page(source)
            first = parsed.to_dict()
            _atomic_write_json(post_dir / "1.json", first)
            cached_pages[1] = first

        total_pages = first.get("total_pages", 1)
        if not isinstance(total_pages, int) or total_pages < 1:
            raise FetchError(f"楼中楼 {post.pid} 的分页信息无效")
        for page_number in range(2, total_pages + 1):
            if page_number in cached_pages:
                continue
            source, _ = fetch(
                f"lzl=1&tid={thread_id}&pid={post.pid}&pn={page_number}"
            )
            parsed = parse_lzl_page(source)
            cached_pages[page_number] = parsed.to_dict()
            _atomic_write_json(post_dir / f"{page_number}.json", parsed.to_dict())

        replies: list[NestedReply] = []
        for page_number in sorted(cached_pages):
            values = cached_pages[page_number].get("replies", [])
            if not isinstance(values, list):
                continue
            replies.extend(
                NestedReply(
                    pid=str(reply.get("pid", "")),
                    author=str(reply.get("author", "")),
                    content=str(reply.get("content", "")),
                )
                for reply in values
                if isinstance(reply, dict)
            )
        _merge_nested_replies(post, replies)
        if post.pid not in completed:
            completed.append(post.pid)
        manifest["updated_at"] = _timestamp()
        _atomic_write_json(export_dir / "manifest.json", manifest)


def export_thread(
    value: str,
    *,
    output_dir: Path | str | None = None,
    include_lzl: bool = False,
    delay: float = 1.0,
    fetcher: Fetcher | None = None,
) -> Path:
    """Export every main-thread page and optionally every nested reply."""

    if delay < 0:
        raise ValueError("请求间隔不能为负数")
    thread_id = extract_thread_id(value)
    export_dir = Path(output_dir) if output_dir is not None else _default_output_dir(thread_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = export_dir / "manifest.json"
    result_path = export_dir / "thread.json"

    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        if str(manifest.get("thread_id", "")) != thread_id:
            raise ValueError("输出目录属于另一个贴吧帖子")
        if manifest.get("status") == "complete" and result_path.exists():
            completed_with_lzl = bool(manifest.get("include_lzl"))
            if completed_with_lzl or not include_lzl:
                return result_path
    else:
        manifest = {
            "schema_version": 1,
            "thread_id": thread_id,
            "source_endpoint": MOBILE_THREAD_URL,
            "status": "incomplete",
            "include_lzl": False,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "completed_page_offsets": [],
            "completed_lzl_pids": [],
        }
        _atomic_write_json(manifest_path, manifest)

    if fetcher is None:
        from .fetching import fetch_tieba_html

        fetcher = fetch_tieba_html
    fetch = _PacedFetcher(fetcher, delay)
    pages_dir = export_dir / "pages"
    pages = _load_cached_pages(pages_dir)

    try:
        first_page = pages.get(0)
        if first_page is None:
            source, _ = fetch(thread_id)
            first_page = parse_thread_page(source, thread_id)
            if first_page.offset != 0:
                raise FetchError("贴吧首屏返回了异常的分页偏移量")
            pages[0] = first_page
            _atomic_write_json(pages_dir / "0.json", first_page.to_dict())

        page_size = first_page.page_size
        total_pages = first_page.total_pages
        if page_size < 1 or total_pages < 1:
            raise FetchError("贴吧帖子分页信息无效")
        for offset in range(page_size, page_size * total_pages, page_size):
            if offset in pages:
                continue
            source, _ = fetch(f"{thread_id}&pn={offset}")
            page = parse_thread_page(source, thread_id)
            if page.offset != offset:
                raise FetchError(
                    f"贴吧返回页偏移量 {page.offset}，预期为 {offset}"
                )
            pages[offset] = page
            _atomic_write_json(pages_dir / f"{offset}.json", page.to_dict())
            manifest["completed_page_offsets"] = sorted(pages)
            manifest["updated_at"] = _timestamp()
            _atomic_write_json(manifest_path, manifest)

        posts = _ordered_posts(pages)
        _atomic_write_jsonl(
            export_dir / "posts.jsonl",
            [post.to_dict() for post in posts],
        )
        manifest.update(
            {
                "title": first_page.title,
                "forum_name": first_page.forum_name,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_posts": first_page.total_posts,
                "completed_page_offsets": sorted(pages),
                "updated_at": _timestamp(),
            }
        )
        _atomic_write_json(manifest_path, manifest)

        if include_lzl:
            _export_nested_replies(thread_id, posts, export_dir, fetch, manifest)

        _atomic_write_jsonl(
            export_dir / "posts.jsonl",
            [post.to_dict() for post in posts],
        )
        completed_at = _timestamp()
        result = {
            "schema_version": 1,
            "thread": {
                "id": thread_id,
                "title": first_page.title,
                "forum_name": first_page.forum_name,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_posts": first_page.total_posts,
            },
            "export": {
                "status": "complete",
                "captured_at": completed_at,
                "include_lzl": include_lzl,
                "source_endpoint": MOBILE_THREAD_URL,
            },
            "posts": [post.to_dict() for post in posts],
        }
        _atomic_write_json(result_path, result)
        manifest.update(
            {
                "status": "complete",
                "include_lzl": include_lzl,
                "updated_at": completed_at,
            }
        )
        _atomic_write_json(manifest_path, manifest)
        return result_path
    except (ValueError, OSError, FetchError):
        manifest["status"] = "incomplete"
        manifest["updated_at"] = _timestamp()
        _atomic_write_json(manifest_path, manifest)
        raise


def export_cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tieba_cli export",
        description="将贴吧旧移动端帖子完整导出为 JSON。",
    )
    parser.add_argument("thread", help="贴吧帖子 ID 或受支持的帖子 URL")
    parser.add_argument("--output", type=Path, help="导出目录")
    parser.add_argument(
        "--include-lzl",
        action="store_true",
        help="逐页抓取未完整嵌入正文的楼中楼",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="连续请求的最小间隔秒数（默认：1.0）",
    )
    args = parser.parse_args(argv)
    try:
        result = export_thread(
            args.thread,
            output_dir=args.output,
            include_lzl=args.include_lzl,
            delay=args.delay,
        )
    except (ValueError, OSError, FetchError) as exc:
        parser.exit(1, f"tieba-export: {exc}\n")
    sys.stdout.write(f"{result}\n")
    return 0
