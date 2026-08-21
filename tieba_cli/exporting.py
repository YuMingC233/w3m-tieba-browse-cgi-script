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

from .constants import CURRENT_THREAD_URL, MOBILE_THREAD_URL
from .current_api import CurrentNestedReplyPage, CurrentTiebaClient
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
            author_id=str(reply.get("author_id", "")),
            posted_at=str(reply.get("posted_at", "")),
            content_text=(
                str(reply.get("content_text", ""))
                if not isinstance(reply.get("content"), str)
                else str(reply.get("content", ""))
            ),
            content=(
                [item for item in reply.get("content", []) if isinstance(item, dict)]
                if isinstance(reply.get("content"), list)
                else [{"type": "text", "text": str(reply.get("content", ""))}]
            ),
            content_html=str(reply.get("content_html", "")),
        )
        for reply in nested_values
        if isinstance(reply, dict)
    ] if isinstance(nested_values, list) else []
    floor = value.get("floor")
    return Post(
        pid=str(value.get("pid", "")),
        floor=floor if isinstance(floor, int) else None,
        author=str(value.get("author", "")),
        author_id=str(value.get("author_id", "")),
        posted_at=str(value.get("posted_at", "")),
        content_text=(
            str(value.get("content_text", ""))
            if not isinstance(value.get("content"), str)
            else str(value.get("content", ""))
        ),
        content=(
            [item for item in value.get("content", []) if isinstance(item, dict)]
            if isinstance(value.get("content"), list)
            else [{"type": "text", "text": str(value.get("content", ""))}]
        ),
        content_html=str(value.get("content_html", "")),
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
            item.author == reply.author and item.content_text == reply.content_text
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
                    author_id=str(reply.get("author_id", "")),
                    posted_at=str(reply.get("posted_at", "")),
                    content_text=(
                        str(reply.get("content_text", ""))
                        if not isinstance(reply.get("content"), str)
                        else str(reply.get("content", ""))
                    ),
                    content=(
                        [item for item in reply.get("content", []) if isinstance(item, dict)]
                        if isinstance(reply.get("content"), list)
                        else [{"type": "text", "text": str(reply.get("content", ""))}]
                    ),
                    content_html=str(reply.get("content_html", "")),
                )
                for reply in values
                if isinstance(reply, dict)
            )
        _merge_nested_replies(post, replies)
        if post.pid not in completed:
            completed.append(post.pid)
        manifest["updated_at"] = _timestamp()
        _atomic_write_json(export_dir / "manifest.json", manifest)


def _export_legacy_thread(
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
            "schema_version": 2,
            "thread_id": thread_id,
            "source": "legacy",
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
            "schema_version": 2,
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
                "source": "legacy",
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


def _current_nested_page_from_dict(
    value: dict[str, object],
) -> CurrentNestedReplyPage:
    raw_replies = value.get("replies", [])
    replies: list[NestedReply] = []
    if isinstance(raw_replies, list):
        for raw_reply in raw_replies:
            if not isinstance(raw_reply, dict):
                continue
            content = raw_reply.get("content", [])
            replies.append(
                NestedReply(
                    pid=str(raw_reply.get("pid", "")),
                    author=str(raw_reply.get("author", "")),
                    author_id=str(raw_reply.get("author_id", "")),
                    posted_at=str(raw_reply.get("posted_at", "")),
                    content_text=str(raw_reply.get("content_text", "")),
                    content=(
                        [item for item in content if isinstance(item, dict)]
                        if isinstance(content, list)
                        else []
                    ),
                    content_html=str(raw_reply.get("content_html", "")),
                )
            )
    next_offset = value.get("next_offset", 0)
    return CurrentNestedReplyPage(
        replies=replies,
        next_offset=next_offset if isinstance(next_offset, int) else 0,
        has_more=bool(value.get("has_more")),
    )


def _export_current_thread(
    value: str,
    *,
    client: CurrentTiebaClient,
    output_dir: Path | str | None,
    include_lzl: bool,
    delay: float,
) -> Path:
    thread_id = extract_thread_id(value)
    export_dir = Path(output_dir) if output_dir is not None else _default_output_dir(thread_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = export_dir / "current"
    pages_dir = cache_dir / "pages"
    manifest_path = cache_dir / "manifest.json"
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
            "schema_version": 2,
            "thread_id": thread_id,
            "source": "current",
            "source_endpoint": CURRENT_THREAD_URL,
            "status": "incomplete",
            "include_lzl": False,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "completed_pages": [],
            "completed_lzl_pids": [],
        }
        _atomic_write_json(manifest_path, manifest)

    pages: dict[int, ThreadPage] = {}
    if pages_dir.exists():
        for path in pages_dir.glob("*.json"):
            if path.stem.isdigit():
                pages[int(path.stem)] = _page_from_dict(_read_json(path))

    last_request: float | None = None

    def pace() -> None:
        nonlocal last_request
        if last_request is not None and delay:
            remaining = delay - (time.monotonic() - last_request)
            if remaining > 0:
                time.sleep(remaining)
        last_request = time.monotonic()

    def fetch_page(page_number: int) -> ThreadPage:
        pace()
        return client.fetch_thread_page(thread_id, page_number)

    def fetch_nested(post_id: str, offset: int) -> CurrentNestedReplyPage:
        pace()
        return client.fetch_nested_page(thread_id, post_id, offset)

    try:
        first_page = pages.get(1)
        if first_page is None:
            first_page = fetch_page(1)
            if first_page.current_page != 1:
                raise FetchError("贴吧新版接口首页页码异常")
            pages[1] = first_page
            _atomic_write_json(pages_dir / "1.json", first_page.to_dict())

        total_pages = first_page.total_pages
        if total_pages < 1:
            raise FetchError("贴吧新版接口分页信息无效")
        for page_number in range(2, total_pages + 1):
            if page_number in pages:
                continue
            page = fetch_page(page_number)
            if page.current_page != page_number:
                raise FetchError(
                    f"贴吧返回页码 {page.current_page}，预期为 {page_number}"
                )
            pages[page_number] = page
            _atomic_write_json(pages_dir / f"{page_number}.json", page.to_dict())
            manifest["completed_pages"] = sorted(pages)
            manifest["updated_at"] = _timestamp()
            _atomic_write_json(manifest_path, manifest)

        posts = _ordered_posts(pages)
        manifest.update(
            {
                "title": first_page.title,
                "forum_name": first_page.forum_name,
                "total_pages": total_pages,
                "total_posts": first_page.total_posts,
                "completed_pages": sorted(pages),
                "updated_at": _timestamp(),
            }
        )
        _atomic_write_json(manifest_path, manifest)

        if include_lzl:
            completed = manifest.setdefault("completed_lzl_pids", [])
            if not isinstance(completed, list):
                raise FetchError("导出清单中的楼中楼进度无效")
            for post in posts:
                if not post.pid or post.nested_reply_count <= len(post.nested_replies):
                    continue
                offset = len(post.nested_replies)
                post_dir = cache_dir / "lzl" / post.pid
                while len(post.nested_replies) < post.nested_reply_count:
                    cache_path = post_dir / f"{offset}.json"
                    if cache_path.exists():
                        nested_page = _current_nested_page_from_dict(
                            _read_json(cache_path)
                        )
                    else:
                        nested_page = fetch_nested(post.pid, offset)
                        _atomic_write_json(cache_path, nested_page.to_dict())
                    _merge_nested_replies(post, nested_page.replies)
                    if not nested_page.has_more:
                        break
                    if nested_page.next_offset <= offset:
                        raise FetchError(
                            f"楼中楼 {post.pid} 返回了无效的 offset"
                        )
                    offset = nested_page.next_offset
                if post.pid not in completed:
                    completed.append(post.pid)
                manifest["updated_at"] = _timestamp()
                _atomic_write_json(manifest_path, manifest)

        _atomic_write_jsonl(
            export_dir / "posts.jsonl", [post.to_dict() for post in posts]
        )
        completed_at = _timestamp()
        result = {
            "schema_version": 2,
            "thread": {
                "id": thread_id,
                "title": first_page.title,
                "forum_name": first_page.forum_name,
                "total_pages": total_pages,
                "total_posts": first_page.total_posts,
            },
            "export": {
                "status": "complete",
                "captured_at": completed_at,
                "include_lzl": include_lzl,
                "source": "current",
                "source_endpoint": CURRENT_THREAD_URL,
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
        _atomic_write_json(export_dir / "manifest.json", manifest)
        return result_path
    except (ValueError, OSError, FetchError):
        manifest["status"] = "incomplete"
        manifest["updated_at"] = _timestamp()
        _atomic_write_json(manifest_path, manifest)
        raise


def export_thread(
    value: str,
    *,
    output_dir: Path | str | None = None,
    include_lzl: bool = False,
    delay: float = 1.0,
    fetcher: Fetcher | None = None,
    source: str = "auto",
    current_client: CurrentTiebaClient | None = None,
) -> Path:
    """Export a thread, preferring the current authenticated JSON API."""

    if delay < 0:
        raise ValueError("请求间隔不能为负数")
    if source not in {"auto", "current", "legacy"}:
        raise ValueError("source 必须是 auto、current 或 legacy")

    should_try_current = source in {"auto", "current"}
    if source == "auto" and fetcher is not None and current_client is None:
        should_try_current = False
    if should_try_current:
        try:
            client = current_client or CurrentTiebaClient.from_env()
            return _export_current_thread(
                value,
                client=client,
                output_dir=output_dir,
                include_lzl=include_lzl,
                delay=delay,
            )
        except FetchError:
            if source == "current":
                raise

    return _export_legacy_thread(
        value,
        output_dir=output_dir,
        include_lzl=include_lzl,
        delay=delay,
        fetcher=fetcher,
    )


def export_cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tieba_cli export",
        description="优先使用贴吧新版接口将帖子完整导出为 JSON。",
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
    parser.add_argument(
        "--source",
        choices=("auto", "current", "legacy"),
        default="auto",
        help="数据源：auto 优先新接口并自动回退（默认）",
    )
    args = parser.parse_args(argv)
    try:
        result = export_thread(
            args.thread,
            output_dir=args.output,
            include_lzl=args.include_lzl,
            delay=args.delay,
            source=args.source,
        )
    except (ValueError, OSError, FetchError) as exc:
        parser.exit(1, f"tieba-export: {exc}\n")
    sys.stdout.write(f"{result}\n")
    return 0
