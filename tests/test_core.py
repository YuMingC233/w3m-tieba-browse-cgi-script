import unittest

from tieba_filter import (
    _build_upstream_url,
    add_forum_pagination,
    extract_thread_id,
    filter_tieba_html,
)


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

    def test_filter_removes_tieba_chrome_and_preserves_reading_content(self):
        source = """
        <!DOCTYPE html>
        <html><body>
          <div class="wake_app_tip">取消</div>
          <div class="pb_new_popup">设置精华贴 取消 完成</div>
          <div class="appPromote"><img alt="tieba_log">贴吧App 立即打开</div>
          <div class="jump_page_pop_common">跳页弹窗img立即启动</div>
          <article>
            <img class="user_img" alt="头像" src="avatar.jpg">
            <a class="author" href="/home/main?un=test">贴吧用户_QJNt3D2</a>
            <time>2025-12-10</time>
            <div class="list_item_more_operation">操作 收藏 回复 举报</div>
            <div class="content">
              正文应该保留
              <a href="/p/10955913270?lp=5028&amp;mo_device=1&amp;is_jingpost=0">
                正文链接
              </a>
              <img src="/editor/images/client/image_emoticon1.png">
            </div>
            <div class="fr_list">
              <span class="floor_content">已展示的楼中楼应该保留</span>
              <span class="lzl_cut_more_btn">打开APP查看53条评论</span>
            </div>
            <div class="father-cut-daoliu-normal-box">
              <button>打开贴吧App，查看全部53条评论</button>
            </div>
          </article>
        </body></html>
        """

        result = filter_tieba_html(
            source,
            base_url=(
                "https://tieba.baidu.com/mo/q---1-3-0--2/m?"
                "kw=%E5%AD%99%E7%AC%91%E5%B7%9D"
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
        ):
            self.assertIn(useful, result)


if __name__ == "__main__":
    unittest.main()
