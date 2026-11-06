"""Playwright 爬虫：独立负责列表页、分页与详情页采集。"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from .base_crawler import BaseCrawler
from .config import PAGE_TIMEOUT, PLAYWRIGHT_CSV
from .models import TaskState


class PlaywrightCrawler(BaseCrawler):
    framework = "playwright"

    def __init__(self, state: TaskState, max_pages: int):
        super().__init__(state, PLAYWRIGHT_CSV, max_pages)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _open(self) -> None:
        self._pw = sync_playwright().start()
        try:
            # 优先使用 Playwright 自带 chromium
            self._browser = self._pw.chromium.launch(headless=True)
        except Exception:
            # 未执行 playwright install 时，退回系统 Chrome
            self.logger.warning("未找到 Playwright chromium，改用系统 Chrome")
            self._browser = self._pw.chromium.launch(headless=True, channel="chrome")
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
        )
        # 拦截 Disqus 等第三方资源：本网络不可达会拖慢页面加载，且评论数走独立接口获取
        self._context.route(
            re.compile(r"disqus\.com|dsq_sync|count\.js"),
            lambda route: route.abort(),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(PAGE_TIMEOUT)
        self.logger.info("Playwright 浏览器已启动")

    def _get_html(self, url: str) -> str:
        self._page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        return self._page.content()

    def _close(self) -> None:
        for resource in (self._context, self._browser):
            try:
                if resource:
                    resource.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self.logger.info("Playwright 浏览器已关闭")
