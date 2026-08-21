"""Authenticated client for Tieba's current PC thread JSON endpoints."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .constants import (
    CURRENT_PC_SIGN_SALT,
    CURRENT_THREAD_URL,
)
from .errors import FetchError, ThreadNotFoundError
from .models import NestedReply, Post, ThreadPage


JsonRequester = Callable[
    [str, str, dict[str, str], bytes | None], dict[str, Any]
]


@dataclass
class CurrentNestedReplyPage:
    replies: list[NestedReply] = field(default_factory=list)
    next_offset: int = 0
    has_more: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "replies": [reply.to_dict() for reply in self.replies],
            "next_offset": self.next_offset,
            "has_more": self.has_more,
        }


def _content_text(content: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in content:
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
        media = item.get("media")
        if isinstance(media, list) and media:
            parts.append("[图片]")
        elif isinstance(item.get("origin_src"), str):
            parts.append("[图片]")
    return "\n".join(parts)


def _rich_content(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return copy.deepcopy([item for item in value if isinstance(item, dict)])


class CurrentTiebaClient:
    """Fetch signed pages without exposing the login cookie to output files."""

    def __init__(
        self,
        cookie: str,
        *,
        request_json: JsonRequester | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not cookie.strip():
            raise FetchError("未设置 BAIDU_COOKIE，无法使用贴吧新版接口")
        self.cookie = cookie.strip()
        self.timeout = timeout
        self._request_json_impl = request_json or self._default_request_json
        self._tbs: str | None = None

    @classmethod
    def from_env(cls) -> "CurrentTiebaClient":
        cookie = os.environ.get("BAIDU_COOKIE", "").strip()
        if not cookie:
            candidates = [Path.cwd() / ".env"]
            project_env = Path(__file__).resolve().parent.parent / ".env"
            if project_env not in candidates:
                candidates.append(project_env)
            for path in candidates:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise FetchError(f"无法读取 Cookie 配置：{path}") from exc
                for line in lines:
                    if line.strip().startswith("BAIDU_COOKIE="):
                        cookie = line.split("=", 1)[1].strip()
                        if len(cookie) >= 2 and cookie[0] == cookie[-1] and cookie[0] in {'"', "'"}:
                            cookie = cookie[1:-1]
                        break
                if cookie:
                    break
        return cls(cookie)

    @property
    def source_endpoint(self) -> str:
        return CURRENT_THREAD_URL

    def _headers(self, referer: str = "https://tieba.baidu.com/") -> dict[str, str]:
        return {
            "Cookie": self.cookie,
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) "
                "Gecko/20100101 Firefox/152.0"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://tieba.baidu.com",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        }

    def _default_request_json(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> dict[str, Any]:
        url = urllib.parse.urljoin("https://tieba.baidu.com", path)
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ThreadNotFoundError(
                    "贴吧新版接口明确返回 404，帖子可能已被删除"
                ) from exc
            raise FetchError(
                f"贴吧新版接口请求失败：HTTP {exc.code} {path}"
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise FetchError(f"贴吧新版接口请求失败：{path}") from exc
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise FetchError("贴吧新版接口返回了无法识别的 JSON") from exc
        if not isinstance(value, dict):
            raise FetchError("贴吧新版接口返回格式异常")
        return value

    def _get_tbs(self) -> str:
        if self._tbs:
            return self._tbs
        payload = self._request_json_impl(
            "GET", "/dc/common/tbs", self._headers(), None
        )
        tbs = payload.get("tbs")
        if payload.get("is_login") not in (1, "1") or not isinstance(tbs, str) or not tbs:
            raise FetchError("BAIDU_COOKIE 登录态无效或已过期")
        self._tbs = tbs
        return tbs

    def _signed_post(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        signed = {name: str(value) for name, value in params.items()}
        signed.update(
            {
                "tbs": self._get_tbs(),
                "subapp_type": "pc",
                "_client_type": "20",
            }
        )
        material = "".join(
            f"{name}={signed[name]}" for name in sorted(signed)
        ) + CURRENT_PC_SIGN_SALT
        signed["sign"] = hashlib.md5(material.encode("utf-8")).hexdigest()
        body = urllib.parse.urlencode(signed).encode("utf-8")
        payload = self._request_json_impl(
            "POST", path, self._headers(), body
        )
        code = payload.get("error_code", payload.get("no"))
        if code not in (0, "0"):
            message = payload.get("error_msg") or payload.get("error") or "未知错误"
            raise FetchError(f"贴吧新版接口返回异常：{code} {message}")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    @staticmethod
    def _users(payload: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        values = payload.get("user_list")
        if not isinstance(values, list):
            return result
        for user in values:
            if not isinstance(user, dict):
                continue
            user_id = str(user.get("id", ""))
            if user_id:
                result[user_id] = str(user.get("name_show") or user.get("name") or "")
        return result

    @staticmethod
    def _reply(value: dict[str, Any], users: dict[str, str]) -> NestedReply:
        content = _rich_content(value.get("content"))
        author_id = str(value.get("author_id", ""))
        author_value = value.get("author")
        author = ""
        if isinstance(author_value, dict):
            author = str(author_value.get("name_show") or author_value.get("name") or "")
        return NestedReply(
            pid=str(value.get("id", "")),
            author=author or users.get(author_id, ""),
            author_id=author_id,
            posted_at=str(value.get("time", "")),
            content_text=_content_text(content),
            content=content,
        )

    @classmethod
    def _post(cls, value: dict[str, Any], users: dict[str, str]) -> Post:
        content = _rich_content(value.get("content"))
        author_id = str(value.get("author_id", ""))
        embedded: list[NestedReply] = []
        sub_posts = value.get("sub_post_list")
        if isinstance(sub_posts, dict):
            nested_values = sub_posts.get("sub_post_list")
            if isinstance(nested_values, list):
                embedded = [
                    cls._reply(item, users)
                    for item in nested_values
                    if isinstance(item, dict)
                ]
        floor = value.get("floor")
        return Post(
            pid=str(value.get("id", "")),
            floor=floor if isinstance(floor, int) else None,
            author=users.get(author_id, ""),
            author_id=author_id,
            posted_at=str(value.get("time", "")),
            content_text=_content_text(content),
            content=content,
            nested_reply_count=(
                value.get("sub_post_number", 0)
                if isinstance(value.get("sub_post_number", 0), int)
                else 0
            ),
            nested_replies=embedded,
        )

    def fetch_thread_page(self, thread_id: str, page_number: int) -> ThreadPage:
        if page_number < 1:
            raise ValueError("贴子页码必须是正整数")
        payload = self._signed_post(
            "/c/f/pb/page_pc",
            {
                "pn": page_number,
                "lz": 0,
                "r": 2 if page_number == 1 else 0,
                "mark_type": 0,
                "back": 0,
                "fr": "",
                "kz": thread_id,
                "session_request_times": 1,
            },
        )
        users = self._users(payload)
        posts: list[Post] = []
        first_floor = payload.get("first_floor")
        if page_number == 1 and isinstance(first_floor, dict):
            posts.append(self._post(first_floor, users))
        values = payload.get("post_list")
        if isinstance(values, list):
            posts.extend(
                self._post(item, users) for item in values if isinstance(item, dict)
            )
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        thread = payload.get("thread") if isinstance(payload.get("thread"), dict) else {}
        forum = payload.get("forum") if isinstance(payload.get("forum"), dict) else {}
        current_page = page.get("current_page")
        total_pages = page.get("total_page")
        if not isinstance(current_page, int) or not isinstance(total_pages, int):
            raise FetchError("贴吧新版接口分页信息无效")
        total_posts = thread.get("valid_post_num", thread.get("reply_num", len(posts)))
        return ThreadPage(
            thread_id=thread_id,
            title=str(thread.get("title", "")),
            forum_name=str(forum.get("name", "")),
            page_size=len(posts),
            offset=page_number - 1,
            current_page=current_page,
            total_pages=total_pages,
            total_posts=total_posts if isinstance(total_posts, int) else len(posts),
            posts=posts,
        )

    def fetch_nested_page(
        self, thread_id: str, post_id: str, offset: int
    ) -> CurrentNestedReplyPage:
        if offset < 0:
            raise ValueError("楼中楼 offset 不能为负数")
        payload = self._signed_post(
            "/c/f/pb/nestedFloor",
            {"post_id": post_id, "thread_id": thread_id, "offset": offset},
        )
        users = self._users(payload)
        values = payload.get("post_list")
        replies = [
            self._reply(item, users)
            for item in values
            if isinstance(item, dict)
        ] if isinstance(values, list) else []
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        next_offset = page.get("offset", offset + len(replies))
        if not isinstance(next_offset, int):
            raise FetchError("贴吧楼中楼接口 offset 无效")
        return CurrentNestedReplyPage(
            replies=replies,
            next_offset=next_offset,
            has_more=page.get("has_more") in (1, "1", True),
        )
