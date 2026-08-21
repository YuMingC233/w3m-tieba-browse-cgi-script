"""Simplify Tieba HTML for terminal rendering."""

from __future__ import annotations

import html
import urllib.parse
from html.parser import HTMLParser

from .constants import CGI_URL, DROP_CLASSES, DROP_IDS, VOID_ELEMENTS
from .routing import extract_thread_id, safe_upstream_params


def _cgi_href_for_tieba_url(href: str, base_url: str) -> str:
    absolute = urllib.parse.urljoin(base_url, html.unescape(href))
    try:
        thread_id = extract_thread_id(absolute)
    except ValueError:
        return href

    query = urllib.parse.urlencode(safe_upstream_params(absolute))
    return f"{CGI_URL}{thread_id}" + (f"&{query}" if query else "")


class _TiebaHTMLFilter(HTMLParser):
    def __init__(self, *, base_url: str | None, rewrite_links: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.rewrite_links = rewrite_links
        self.output: list[str] = []
        self.skip_depth = 0
        self.base_written = False
        self.li_depth = 0
        self.current_post_pid: str | None = None
        self.current_post_li_depth: int | None = None
        self.current_lzl_total: int | None = None
        self.thread_id: str | None = None
        if base_url:
            try:
                self.thread_id = extract_thread_id(base_url)
            except ValueError:
                pass

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

        attr_map = self._attr_map(attrs)
        classes = set(attr_map.get("class", "").split())
        if tag == "li":
            self.li_depth += 1
            if "post_list_item" in classes and attr_map.get("tid", "").isdigit():
                self.current_post_pid = attr_map["tid"]
                self.current_post_li_depth = self.li_depth
                self.current_lzl_total = None

        if tag == "div" and "fr_list" in classes:
            count = attr_map.get("data-list-count", "")
            self.current_lzl_total = int(count) if count.isdigit() else None

        if tag == "span" and "lzl_cut_more_btn" in classes:
            if self.thread_id and self.current_post_pid:
                query = urllib.parse.urlencode(
                    {
                        "lzl": "1",
                        "tid": self.thread_id,
                        "pid": self.current_post_pid,
                        "pn": "1",
                    }
                )
                total = (
                    f" {self.current_lzl_total} 条"
                    if self.current_lzl_total is not None
                    else ""
                )
                href = html.escape(f"{CGI_URL}{query}", quote=True)
                self.output.append(f'<a href="{href}">查看全部{total}楼中楼</a>')
            self.skip_depth = 1
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
        tag = tag.lower()
        self.output.append(f"</{tag}>")
        if tag == "li":
            if self.current_post_li_depth == self.li_depth:
                self.current_post_pid = None
                self.current_post_li_depth = None
                self.current_lzl_total = None
            self.li_depth = max(0, self.li_depth - 1)

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
