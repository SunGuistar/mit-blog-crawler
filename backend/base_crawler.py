"""双框架共享的爬取主流程。

具体框架（Playwright / DrissionPage）只需实现三个浏览器原语：
- _open()   启动浏览器
- _get_html(url)  获取页面 HTML
- _close()  释放浏览器资源

列表解析、详情字段提取、评论数获取、重试、断点续爬、CSV 保存、
进度上报均为共享逻辑，但每个任务持有独立的 state / exporter / 浏览器实例。
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

from .config import (
    BLOGS_URL,
    LOGS_DIR,
    MAX_RETRIES,
    PAGE_TIMEOUT,
    REQUEST_DELAY,
)
from .csv_exporter import CsvExporter
from .models import ArticleRecord, TaskState
from .parser import parse_detail_page, parse_list_page


def _make_logger(framework: str) -> logging.Logger:
    logger = logging.getLogger(f"crawler.{framework}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(LOGS_DIR / f"{framework}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def fetch_comment_count(disqus_identifier: Optional[str], logger: logging.Logger) -> tuple:
    """获取 Disqus 评论总数。

    返回 (count 字符串或 "", 说明)。
    无法获取时返回 ("", 原因说明)，绝不伪造为 0；
    接口可达且确认为 0 时才返回 "0"。
    """
    if not disqus_identifier:
        return "", "页面未找到 Disqus identifier，评论数未获取"
    forum = "mitadmissions"
    url = f"https://{forum}.disqus.com/count-data.js?1={requests.utils.quote(disqus_identifier, safe='')}"
    try:
        resp = requests.get(url, timeout=8, headers={"Referer": "https://mitadmissions.org/"})
        m = re.search(r"WIDGETS\s*\[\s*['\"]1['\"]\s*\]\s*=\s*\{[^}]*count['\"]?\s*:\s*(\d+)", resp.text)
        if m:
            return m.group(1), "Disqus count-data.js"
        return "", f"Disqus 接口响应异常（HTTP {resp.status_code}），评论数未获取"
    except Exception as exc:
        return "", f"Disqus 不可达（{type(exc).__name__}），评论数未获取"


class BaseCrawler(threading.Thread):
    """爬虫线程基类：run() 内是完整的列表->分页->详情->保存流程。"""

    framework: str = "base"

    def __init__(self, state: TaskState, csv_path: Path, max_pages: int):
        super().__init__(name=f"crawler-{self.framework}", daemon=True)
        self.state = state
        self.exporter = CsvExporter(csv_path)
        self.max_pages = max_pages  # 0 = 全部分页
        self._per_page = 16         # 首页实际篇数会覆盖该默认值
        self._disqus_down = False   # 评论接口熔断标记
        self._disqus_skipped = 0
        self.logger = _make_logger(self.framework)

    # ---------- 框架相关原语（子类实现） ----------

    def _open(self) -> None:
        raise NotImplementedError

    def _get_html(self, url: str) -> str:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    # ---------- 共享流程 ----------

    def run(self) -> None:
        state = self.state
        state.task_id = uuid.uuid4().hex[:12]
        state.status = "running"
        state.started_at = time.time()
        self.logger.info("任务启动 %s，模式：%s", state.task_id,
                         "全部分页" if self.max_pages == 0 else f"前 {self.max_pages} 页")

        # 断点续爬：恢复已采集 URL 与成功计数
        done_urls = self.exporter.done_urls()
        state.success_count = self.exporter.count()
        if done_urls:
            self.logger.info("断点续爬：跳过已完成 %d 篇", len(done_urls))

        try:
            self._open()
            self._crawl_pages(done_urls)
            if state.status == "running":
                state.status = "finished"
                self.logger.info("任务完成：成功 %d，失败 %d", state.success_count, state.failed_count)
        except Exception as exc:  # 单框架异常不得影响另一框架
            state.status = "error"
            state.error_message = f"{type(exc).__name__}: {exc}"
            self.logger.exception("任务异常终止")
        finally:
            try:
                self._close()
            except Exception:
                self.logger.exception("浏览器资源释放异常")
            if state.status == "running":
                state.status = "finished"
            elif state.status == "stopping":
                state.status = "stopped"

    def _stopping(self) -> bool:
        return self.state.stop_event.is_set()

    # Disqus 熔断：不可达时不再每篇都等待超时，定期重探测
    DISQUS_RETRY_EVERY = 25

    def _comment_count(self, identifier):
        if self._disqus_down:
            self._disqus_skipped += 1
            if self._disqus_skipped % self.DISQUS_RETRY_EVERY == 0:
                self._disqus_down = False  # 定期重探测
            else:
                return "", "Disqus 不可达（本轮已跳过接口请求）"
        count, note = fetch_comment_count(identifier, self.logger)
        if not count and note.startswith("Disqus 不可达"):
            self._disqus_down = True
            self._disqus_skipped = 0
            self.logger.info("Disqus 持续不可达，本轮任务剩余文章默认评论数 0，定期重探测")
        return count, note

    def _crawl_pages(self, done_urls: set) -> None:
        state = self.state
        page_no = 1
        page_url: Optional[str] = BLOGS_URL
        seen: set = set()

        while page_url and not self._stopping():
            self.logger.info("访问列表页 %d: %s", page_no, page_url)
            html = self._fetch_with_retry(page_url, kind="列表页")
            if html is None:
                state.failed_count += 1
                self.logger.error("列表页失败，终止任务: %s", page_url)
                break

            article_urls, next_url = parse_list_page(html, page_url)
            total = _parse_total_pages(html)
            if total:
                state.total_pages = total

            if page_no == 1:
                self._per_page = max(len(article_urls), 1)

            new_urls = [u for u in article_urls if u not in seen]
            seen.update(new_urls)
            state.discovered_count = len(seen)
            state.current_page = page_no

            # 总文章数：最后一页（或设定范围末页）到达前用估算，到达后为精确值
            if self.max_pages:
                if page_no >= self.max_pages:
                    state.total_articles = len(seen)  # 范围末页：精确
                else:
                    state.total_articles = self._per_page * self.max_pages  # 估算
            else:
                if next_url is None:
                    state.total_articles = len(seen)  # 站点末页：精确
                elif state.total_pages:
                    state.total_articles = self._per_page * state.total_pages  # 估算
            self.logger.info("第 %d 页发现 %d 篇文章（累计 %d）", page_no, len(new_urls), len(seen))

            for article_url in new_urls:
                if self._stopping():
                    self.logger.info("收到停止信号，完成当前收尾")
                    break
                if article_url in done_urls or self.exporter.is_done(article_url):
                    continue
                self._crawl_article(article_url)

            if self.max_pages and page_no >= self.max_pages:
                self.logger.info("达到设定分页数 %d，停止翻页", self.max_pages)
                break
            page_no += 1
            page_url = next_url  # None 表示已到最后一页
            if page_url is None:
                state.total_pages = page_no
                self.logger.info("已到达最后一页（第 %d 页）", page_no)

    def _crawl_article(self, url: str) -> None:
        state = self.state
        for attempt in range(1, MAX_RETRIES + 2):  # 首次 + MAX_RETRIES 次重试
            try:
                html = self._fetch_with_retry(url, kind="详情页")
                if html is None:
                    raise RuntimeError("页面获取失败")
                record = parse_detail_page(html, url)
                if not record.title and not record.content:
                    raise RuntimeError("标题与正文均为空，页面结构可能异常")
                count, note = self._comment_count(
                    getattr(record, "_disqus_identifier", None)
                )
                # 按需求：无法获取时 Comment Count 默认值 0（获取失败原因仍记入日志）
                record.comment_count = count if count else "0"
                if note and not count:
                    self.logger.info("评论数默认 0：%s (%s)", note, url)
                state.comment_note = note
                state.current_article = record.title[:60]
                self.exporter.append(record)
                self.exporter.mark_url(url)
                state.success_count += 1
                return
            except Exception as exc:
                self.logger.warning("文章采集失败（第 %d 次）%s: %s", attempt, url, exc)
                if attempt > MAX_RETRIES:
                    state.failed_count += 1
                    self.logger.error("文章放弃: %s", url)
                else:
                    self._polite_delay()

    def _fetch_with_retry(self, url: str, kind: str) -> Optional[str]:
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                html = self._get_html(url)
                self._polite_delay()
                return html
            except Exception as exc:
                self.logger.warning("%s获取失败（第 %d 次）%s: %s", kind, attempt, url, exc)
                if attempt > MAX_RETRIES:
                    return None
                self._polite_delay()

    def _polite_delay(self) -> None:
        time.sleep(random.uniform(*REQUEST_DELAY))


def _parse_total_pages(html: str) -> Optional[int]:
    """从分页链接中解析最大页码（首页即可得知总页数）。"""
    pages = [int(n) for n in re.findall(r"/blogs/page/(\d+)/", html)]
    return max(pages) if pages else None
