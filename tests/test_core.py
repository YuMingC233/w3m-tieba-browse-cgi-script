import json
import tempfile
import unittest
from pathlib import Path

from tieba_filter import (
    FetchError,
    _build_upstream_url,
    add_forum_pagination,
    add_thread_pagination,
    extract_thread_id,
    filter_tieba_html,
    render_lzl_page,
)
from tieba_cli.parsing import parse_lzl_page, parse_thread_page
from tieba_cli.exporting import export_thread


class TiebaFilterTests(unittest.TestCase):
    def test_extract_thread_id_from_supported_tieba_urls(self):
        self.assertEqual(
            extract_thread_id(
                "https://tieba.baidu.com/p/10955297834?lp=5028&mo_device=1"
            ),
            "10955297834",
        )
        self.assertEqual(
            extract_thread_id(
                "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
                "kz=10955297834?lp=5028&mo_device=1"
            ),
            "10955297834",
        )

        with self.assertRaises(ValueError):
            extract_thread_id("https://example.com/p/10955297834")

        self.assertEqual(
            _build_upstream_url(
                "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
                "kw=%E5%AD%99%E7%AC%91%E5%B7%9D&pn=30"
            ),
            "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
            "kw=%E5%AD%99%E7%AC%91%E5%B7%9D&pn=30",
        )

        page_source = """
        <html><body>帖子列表<script>
        conf: {page: {"page_size":30,"offset":30,"current_page":2,
        "total_page":3}}
        </script></body></html>
        """
        paginated = add_forum_pagination(
            page_source,
            "kw=%E5%AD%99%E7%AC%91%E5%B7%9D&pn=30",
        )
        self.assertIn("第 2 / 3 页", paginated)
        self.assertIn("?kw=%E5%AD%99%E7%AC%91%E5%B7%9D&amp;pn=0", paginated)
        self.assertIn("?kw=%E5%AD%99%E7%AC%91%E5%B7%9D&amp;pn=60", paginated)

        thread_source = """
        <html><body>帖子正文<script>
        conf: {page: {"page_size":30,"offset":30,"current_page":2,
        "total_page":19}}
        </script></body></html>
        """
        thread_paginated = add_thread_pagination(
            thread_source,
            "10955297834&pn=30&see_lz=1",
        )
        self.assertIn("第 2 / 19 页", thread_paginated)
        self.assertIn(
            "?10955297834&amp;pn=0&amp;see_lz=1",
            thread_paginated,
        )
        self.assertIn(
            "?10955297834&amp;pn=60&amp;see_lz=1",
            thread_paginated,
        )
        self.assertIn('name="page"', thread_paginated)
        self.assertIn('name="page_size" value="30"', thread_paginated)
        self.assertIn('name="total_page" value="19"', thread_paginated)
        self.assertIn(
            "?10955297834&amp;pn=510&amp;see_lz=1&amp;r=1",
            thread_paginated,
        )

        self.assertEqual(
            _build_upstream_url(
                "kz=10955297834&page=7&page_size=30&total_page=19"
            ),
            "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
            "kz=10955297834&pn=180",
        )
        self.assertEqual(
            _build_upstream_url(
                "kz=10955297834&page=7&page_size=30&total_page=19&r=1"
            ),
            "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
            "kz=10955297834&pn=360&r=1",
        )
        with self.assertRaises(ValueError):
            _build_upstream_url(
                "kz=10955297834&page=20&page_size=30&total_page=19"
            )

        reverse_source = """
        <html><body>倒序帖子正文<script>
        conf: {page: {"page_size":30,"offset":510,"current_page":18,
        "total_page":19}}
        </script></body></html>
        """
        reverse_paginated = add_thread_pagination(
            reverse_source,
            "10955297834&pn=510&see_lz=1&r=1",
        )
        self.assertIn("倒序 · 第 2 / 19 页", reverse_paginated)
        self.assertIn(
            "?10955297834&amp;pn=540&amp;see_lz=1&amp;r=1",
            reverse_paginated,
        )
        self.assertIn(
            "?10955297834&amp;pn=480&amp;see_lz=1&amp;r=1",
            reverse_paginated,
        )
        self.assertIn(
            "?10955297834&amp;pn=30&amp;see_lz=1",
            reverse_paginated,
        )
        self.assertIn('name="r" value="1"', reverse_paginated)

        self.assertEqual(
            _build_upstream_url(
                "lzl=1&tid=10955297834&pid=153847299771&pn=2"
            ),
            "https://tieba.baidu.com/mo/q---1-3-0--2/flr?"
            "pid=153847299771&kz=10955297834&pn=1&fpn=2",
        )
        with self.assertRaises(ValueError):
            _build_upstream_url("lzl=1&tid=10955297834&pid=invalid&pn=1")

        lzl_source = json.dumps(
            {
                "no": 0,
                "data": {
                    "page": {"total_num": 107, "total_page": 11},
                    "floor_html": (
                        '<li class="list_item_floor">'
                        '<a class="user_name">楼中楼用户:</a>'
                        '<span class="floor_content">完整楼中楼内容</span>'
                        "</li>"
                    ),
                },
            },
            ensure_ascii=False,
        )
        lzl_page = render_lzl_page(
            lzl_source,
            "lzl=1&tid=10955297834&pid=153847299771&pn=2",
        )
        self.assertIn("楼中楼用户", lzl_page)
        self.assertIn("完整楼中楼内容", lzl_page)
        self.assertIn("共 107 条 · 第 2 / 11 页", lzl_page)
        self.assertIn("pid=153847299771&amp;pn=1", lzl_page)
        self.assertIn("pid=153847299771&amp;pn=3", lzl_page)
        self.assertNotIn("floor_html", lzl_page)

        parsed_lzl = parse_lzl_page(lzl_source)
        self.assertEqual(parsed_lzl.total_replies, 107)
        self.assertEqual(parsed_lzl.total_pages, 11)
        self.assertEqual(parsed_lzl.replies[0].author, "楼中楼用户")
        self.assertEqual(parsed_lzl.replies[0].content, "完整楼中楼内容")

        export_pages = {
            "10955297834": """
                <html><head><title>导出测试帖</title></head><body>
                <a class="post_title_text">测试吧</a>
                <li tid="100001" fn="1" class="post_list_item"
                    data-info='{"name_show":"楼主"}'>
                  <span class="list_item_time">2026-08-21</span>
                  <div class="content">第一页正文</div>
                  <div class="fr_list" data-list-count="2"></div>
                </li>
                <script>conf: {page: {"page_size":30,"offset":0,
                "current_page":1,"total_page":2,"total_num":2}}</script>
                </body></html>
            """,
            "10955297834&pn=30": """
                <html><head><title>第2/2页,回贴列表-导出测试帖</title></head><body>
                <a class="post_title_text">测试吧</a>
                <li tid="100002" fn="31" class="post_list_item"
                    data-info='{"name_show":"回复者"}'>
                  <span class="list_item_time">2026-08-22</span>
                  <div class="content">第二页正文</div>
                  <div class="fr_list" data-list-count="0"></div>
                </li>
                <script>conf: {page: {"page_size":30,"offset":30,
                "current_page":2,"total_page":2,"total_num":2}}</script>
                </body></html>
            """,
            "lzl=1&tid=10955297834&pid=100001&pn=1": json.dumps(
                {
                    "no": 0,
                    "data": {
                        "page": {"total_num": 2, "total_page": 1},
                        "floor_html": (
                            '<li pid="200001" class="list_item_floor">'
                            '<a class="user_name">甲:</a>'
                            '<span class="floor_content">第一条讨论</span></li>'
                            '<li pid="200002" class="list_item_floor">'
                            '<a class="user_name">乙:</a>'
                            '<span class="floor_content">第二条讨论</span></li>'
                        ),
                    },
                },
                ensure_ascii=False,
            ),
        }
        fetch_calls = []

        def fake_fetch(request_value):
            fetch_calls.append(request_value)
            return export_pages[request_value], _build_upstream_url(request_value)

        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = export_thread(
                "10955297834",
                output_dir=Path(temp_dir),
                include_lzl=True,
                delay=0,
                fetcher=fake_fetch,
            )
            exported = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(exported["thread"]["title"], "导出测试帖")
            self.assertEqual(exported["export"]["status"], "complete")
            self.assertEqual(len(exported["posts"]), 2)
            self.assertEqual(exported["posts"][0]["content"], "第一页正文")
            self.assertEqual(len(exported["posts"][0]["nested_replies"]), 2)
            self.assertEqual(
                exported["posts"][0]["nested_replies"][1]["content"],
                "第二条讨论",
            )
            self.assertEqual(
                exported["export"]["source_endpoint"],
                "https://tieba.baidu.com/mo/q---1-3-0--2/m",
            )
            self.assertEqual(len((Path(temp_dir) / "posts.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()), 2)
            first_fetch_count = len(fetch_calls)
            cached_path = export_thread(
                "10955297834",
                output_dir=Path(temp_dir),
                include_lzl=True,
                delay=0,
                fetcher=fake_fetch,
            )
            self.assertEqual(cached_path, result_path)
            self.assertEqual(len(fetch_calls), first_fetch_count)

            resume_dir = Path(temp_dir) / "resume"
            failed_once = False

            def flaky_fetch(request_value):
                nonlocal failed_once
                fetch_calls.append(request_value)
                if request_value.endswith("&pn=30") and not failed_once:
                    failed_once = True
                    raise FetchError("模拟安全验证")
                return export_pages[request_value], _build_upstream_url(request_value)

            with self.assertRaises(FetchError):
                export_thread(
                    "10955297834",
                    output_dir=resume_dir,
                    delay=0,
                    fetcher=flaky_fetch,
                )
            incomplete_manifest = json.loads(
                (resume_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(incomplete_manifest["status"], "incomplete")
            fetch_calls.clear()
            resumed_path = export_thread(
                "10955297834",
                output_dir=resume_dir,
                delay=0,
                fetcher=flaky_fetch,
            )
            self.assertEqual(fetch_calls, ["10955297834&pn=30"])
            resumed = json.loads(resumed_path.read_text(encoding="utf-8"))
            self.assertEqual(resumed["export"]["status"], "complete")
            self.assertEqual(len(resumed["posts"]), 2)

    def test_filter_removes_tieba_chrome_and_preserves_reading_content(self):
        source = """
        <!DOCTYPE html>
        <html><head><title>值得讨论的测试帖子</title></head><body>
          <div class="wake_app_tip">取消</div>
          <div class="pb_new_popup">设置精华贴 取消 完成</div>
          <div class="appPromote"><img alt="tieba_log">贴吧App 立即打开</div>
          <div class="jump_page_pop_common">跳页弹窗img立即启动</div>
          <article>
           <a class="post_title_text">孙笑川吧</a>
           <li tid="153847299771" fn="11" class="post_list_item"
               data-info='{"name_show":"贴吧用户_QJNt3D2"}'>
            <img class="user_img" alt="头像" src="avatar.jpg">
            <a class="author" href="/home/main?un=test">贴吧用户_QJNt3D2</a>
            <span class="list_item_time">2025-12-10</span>
            <div class="list_item_more_operation">操作 收藏 回复 举报</div>
            <div class="content">
              正文应该保留
              <a href="/p/10955913270?lp=5028&amp;mo_device=1&amp;is_jingpost=0">
                正文链接
              </a>
              <img src="/editor/images/client/image_emoticon1.png">
              <div class="img_desc">下载贴吧APP，马上闯入高清视界</div>
            </div>
            <div class="fr_list" data-list-count="107">
              <li pid="153847300001" class="list_item_floor">
                <a class="user_name">楼中楼用户:</a>
                <span class="floor_content">已展示的楼中楼应该保留</span>
              </li>
              <span class="lzl_cut_more_btn">打开APP查看105条评论</span>
            </div>
            <div class="father-cut-daoliu-normal-box">
              <button>打开贴吧App，查看全部53条评论</button>
            </div>
           </li>
          </article>
        <script>
        conf: {page: {"page_size":30,"offset":0,"current_page":1,
        "total_page":19,"total_num":570}}
        </script></body></html>
        """

        result = filter_tieba_html(
            source,
            base_url=(
                "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
                "kz=10955297834"
            ),
            rewrite_links=True,
        )

        for noise in (
            "取消",
            "设置精华贴",
            "tieba_log",
            "贴吧App",
            "跳页弹窗",
            "头像",
            "操作 收藏 回复 举报",
            "打开APP查看53条评论",
            "打开贴吧App，查看全部53条评论",
            "image_emoticon1.png",
        ):
            self.assertNotIn(noise, result)

        for useful in (
            "贴吧用户_QJNt3D2",
            "2025-12-10",
            "正文应该保留",
            'href="file:/cgi-bin/tieba_filter.py?10955913270"',
            "正文链接",
            "已展示的楼中楼应该保留",
            "查看全部 107 条楼中楼",
            "?lzl=1&amp;tid=10955297834&amp;pid=153847299771&amp;pn=1",
        ):
            self.assertIn(useful, result)

        page = parse_thread_page(source, "10955297834")
        self.assertEqual(page.title, "值得讨论的测试帖子")
        self.assertEqual(page.forum_name, "孙笑川")
        self.assertEqual(page.page_size, 30)
        self.assertEqual(page.total_pages, 19)
        self.assertEqual(page.total_posts, 570)
        self.assertEqual(len(page.posts), 1)
        post = page.posts[0]
        self.assertEqual(post.pid, "153847299771")
        self.assertEqual(post.floor, 11)
        self.assertEqual(post.author, "贴吧用户_QJNt3D2")
        self.assertEqual(post.posted_at, "2025-12-10")
        self.assertIn("正文应该保留", post.content)
        self.assertNotIn("下载贴吧APP", post.content)
        self.assertEqual(post.nested_reply_count, 107)
        self.assertEqual(post.nested_replies[0].pid, "153847300001")
        self.assertEqual(post.nested_replies[0].author, "楼中楼用户")
        self.assertEqual(
            post.nested_replies[0].content,
            "已展示的楼中楼应该保留",
        )


if __name__ == "__main__":
    unittest.main()
