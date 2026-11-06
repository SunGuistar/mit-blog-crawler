"""任务管理器：创建、调度、停止两套相互独立的爬虫任务。"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from .drissionpage_crawler import DrissionPageCrawler
from .models import TaskState
from .playwright_crawler import PlaywrightCrawler


class TaskManager:
    """同时持有 Playwright 与 DrissionPage 两个独立任务。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[str, TaskState] = {
            "playwright": TaskState(framework="playwright"),
            "drissionpage": TaskState(framework="drissionpage"),
        }
        self._threads: Dict[str, threading.Thread] = {}

    def _any_running_unlocked(self) -> bool:
        return any(t.is_alive() for t in self._threads.values())

    def start(self, max_pages: int) -> Dict[str, str]:
        """一次性并行启动两套爬虫；运行中禁止重复启动。

        每次启动都创建全新的 TaskState，避免上一次运行的停止信号
        和统计计数残留到下一次任务。
        """
        with self._lock:
            if self._any_running_unlocked():
                raise RuntimeError("已有采集任务在运行，请先停止")
            self._states = {
                "playwright": TaskState(framework="playwright"),
                "drissionpage": TaskState(framework="drissionpage"),
            }
            crawlers = [
                PlaywrightCrawler(self._states["playwright"], max_pages),
                DrissionPageCrawler(self._states["drissionpage"], max_pages),
            ]
            self._threads = {c.framework: c for c in crawlers}
        # 在锁外启动，两个任务立即并行运行
        for crawler in crawlers:
            crawler.start()
        return {fw: c.state.task_id for fw, c in ((c.framework, c) for c in crawlers)}

    def stop(self) -> None:
        """协作式停止：向两个任务分别发送停止信号，各任务自行收尾保存。"""
        with self._lock:
            for fw, state in self._states.items():
                if state.status == "running":
                    state.status = "stopping"
                    state.stop_event.set()

    def status(self) -> Dict[str, dict]:
        return {fw: s.snapshot() for fw, s in self._states.items()}

    def state(self, framework: str) -> TaskState:
        return self._states[framework]

    def reset(self) -> None:
        """清空任务状态（运行中禁止重置）。"""
        with self._lock:
            if self._any_running_unlocked():
                raise RuntimeError("采集进行中，停止后才能重置")
            self._states = {
                "playwright": TaskState(framework="playwright"),
                "drissionpage": TaskState(framework="drissionpage"),
            }
            self._threads = {}

    def is_running(self) -> bool:
        with self._lock:
            return self._any_running_unlocked()


manager = TaskManager()
