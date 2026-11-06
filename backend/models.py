"""数据模型：文章记录与任务状态。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ArticleRecord:
    """一篇文章的采集结果（六个目标字段 + 内部使用的 URL）。"""

    title: str = ""
    author: str = ""
    comment_count: str = ""      # 空字符串 = 无法获取/无评论，绝不伪造 0
    publish_time: str = ""       # YYYY-MM-DD
    content: str = ""
    images: str = ""             # 多个 URL 用 " | " 分隔
    url: str = ""                # 内部标识：去重 / 断点续爬，不写入 CSV

    def to_csv_row(self) -> dict:
        return {
            "Title": self.title,
            "Author": self.author,
            "Comment Count": self.comment_count,
            "Time": self.publish_time,
            "Article Content": self.content,
            "Images In Article": self.images,
        }


@dataclass
class TaskState:
    """单个爬虫任务的实时状态（线程安全）。"""

    framework: str
    task_id: str = ""
    status: str = "idle"              # idle / running / stopping / stopped / finished / error
    current_page: int = 0
    total_pages: Optional[int] = None  # 末页发现前为 None
    discovered_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    current_article: str = ""
    error_message: str = ""
    started_at: Optional[float] = None
    comment_note: str = ""            # 评论数获取情况说明（如 disqus 不可达）
    total_articles: Optional[int] = None  # 采集范围内的总文章数（估算->精确）

    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def snapshot(self) -> dict:
        with self._lock:
            data = {
                "framework": self.framework,
                "task_id": self.task_id,
                "status": self.status,
                "current_page": self.current_page,
                "total_pages": self.total_pages,
                "discovered_count": self.discovered_count,
                "success_count": self.success_count,
                "failed_count": self.failed_count,
                "current_article": self.current_article,
                "progress": self._progress_unlocked(),
                "error_message": self.error_message,
                "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)) if self.started_at else None,
                "elapsed_time": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "comment_note": self.comment_note,
                "total_articles": self.total_articles,
            }
        return data

    def _progress_unlocked(self) -> dict:
        """进度 = 已采集文章占采集范围总文章的占比。

        总文章数未知时不伪造百分比，只显示已处理数量。
        断点恢复时已处理数可能暂时超过总数，展示封顶 100%。
        """
        processed = self.success_count + self.failed_count
        total = self.total_articles
        if total:
            return {
                "mode": "percent",
                "processed": processed,
                "total": total,
                "discovered": self.discovered_count,
                "percent": round(min(100.0, processed / total * 100), 1),
            }
        return {"mode": "count", "processed": processed, "discovered": self.discovered_count, "percent": None}
