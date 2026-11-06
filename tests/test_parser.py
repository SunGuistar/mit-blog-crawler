"""离线解析器测试：使用真实页面快照（fixtures），不访问网络。

运行: cd Crawler && python -m pytest tests/ -v
或:    cd Crawler && python -m unittest tests.test_parser -v
"""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.parser import parse_detail_page, parse_list_page  # noqa: E402
from backend.config import CSV_FIELDS  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestListPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (FIXTURES / "list_page.html").read_text(encoding="utf-8")
        cls.urls, cls.next_url = parse_list_page(cls.html, "https://mitadmissions.org/blogs/")

    def test_article_urls_found(self):
        self.assertGreaterEqual(len(self.urls), 10)
        for url in self.urls:
            self.assertIn("/blogs/entry/", url)

    def test_next_page(self):
        self.assertEqual(self.next_url, "https://mitadmissions.org/blogs/page/2/")


class TestDetailPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = "https://mitadmissions.org/blogs/entry/bentry-picnic/"
        cls.html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
        cls.record = parse_detail_page(cls.html, cls.url)

    def test_title(self):
        self.assertEqual(self.record.title, "bentry picnic")

    def test_author(self):
        self.assertEqual(self.record.author, "Alejandro B. '30")

    def test_time_format(self):
        self.assertRegex(self.record.publish_time, r"^\d{4}-\d{2}-\d{2}$")

    def test_content_not_empty(self):
        self.assertGreater(len(self.record.content), 200)
        self.assertIn("\n", self.record.content)  # 保留段落换行

    def test_images_from_lazyload_attr(self):
        self.assertNotEqual(self.record.images, "")
        for url in self.record.images.split(" | "):
            self.assertTrue(url.startswith("https://"))
            self.assertIn("800x600", url)  # 真实图片地址而非占位符

    def test_disqus_identifier(self):
        ident = getattr(self.record, "_disqus_identifier", "")
        self.assertTrue(ident.startswith("129863"))

    def test_csv_fields_order(self):
        self.assertEqual(
            list(self.record.to_csv_row().keys()), CSV_FIELDS
        )


if __name__ == "__main__":
    unittest.main()
