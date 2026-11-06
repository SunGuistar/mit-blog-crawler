"""DrissionPage 爬虫：独立负责列表页、分页与详情页采集。

使用 DrissionPage 自带的浏览器控制与页面元素操作能力，
与 Playwright 爬虫完全独立（独立浏览器实例、独立状态、独立 CSV）。
"""

from __future__ import annotations

import time

from DrissionPage import ChromiumOptions, ChromiumPage

from .base_crawler import BaseCrawler
from .config import DRISSIONPAGE_CSV, PAGE_TIMEOUT
from .models import TaskState


class DrissionPageCrawler(BaseCrawler):
    framework = "drissionpage"

    def __init__(self, state: TaskState, max_pages: int):
        super().__init__(state, DRISSIONPAGE_CSV, max_pages)
        self._page: ChromiumPage | None = None

    def _open(self) -> None:
        co = ChromiumOptions()
        co.headless(True)
        # DOMContentLoaded 即返回，避免等待 Disqus 等被墙第三方资源拖慢整页加载
        co.set_load_mode("eager")
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        co.set_argument("--window-size=1366,900")
        co.set_timeouts(page_load=PAGE_TIMEOUT / 1000)
        self._page = ChromiumPage(co)
        self.logger.info("DrissionPage 浏览器已启动")

    def _get_html(self, url: str) -> str:
        self._page.get(url)
        try:
            self._page.wait.doc_loaded()
        except Exception:
            pass
        # 偶发 CDP 根节点未就绪，短暂重试读取页面 HTML
        last_exc: Exception | None = None
        for _ in range(4):
            try:
                return self._page.html
            except Exception as exc:  # DrissionPage CDPError 等
                last_exc = exc
                time.sleep(1)
        raise last_exc  # type: ignore[misc]

    def _close(self) -> None:
        if self._page:
            try:
                self._page.quit()
            except Exception:
                pass
        self.logger.info("DrissionPage 浏览器已关闭")
