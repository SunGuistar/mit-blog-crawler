"""CSV 导出：增量写入、UTF-8 BOM、原子替换，避免读到半成品文件。

每完成一篇文章写入一行；写入时先落临时文件再原子替换，
下载/预览总是读取完整的快照文件。

断点续爬：URL 清单保存在 <csv名>.urls.json，重启任务后自动跳过已采集文章。
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import threading
from pathlib import Path
from typing import List

from .config import CSV_FIELDS
from .models import ArticleRecord


class CsvExporter:
    """单个爬虫专用 CSV 写入器（两套爬虫各持有一个实例，互不覆盖）。"""

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self.tmp_path = self.csv_path.with_name(self.csv_path.name + ".tmp")
        self.checkpoint_path = self.csv_path.with_suffix(".urls.json")
        self._lock = threading.Lock()
        self._rows: List[dict] = []
        self._urls: set = set()
        self._load_checkpoint()
        self._load_existing()

    # ---------- 断点续爬 ----------

    def _load_checkpoint(self) -> None:
        if self.checkpoint_path.exists():
            try:
                self._urls = set(json.loads(self.checkpoint_path.read_text(encoding="utf-8")))
            except Exception:
                self._urls = set()

    def mark_url(self, url: str) -> None:
        """记录已采集 URL 并立即持久化（供断点续爬）。"""
        with self._lock:
            self._urls.add(url)
            self._save_checkpoint_unlocked()

    def _save_checkpoint_unlocked(self) -> None:
        tmp = self.checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(sorted(self._urls)), encoding="utf-8")
        shutil.move(str(tmp), str(self.checkpoint_path))

    def is_done(self, url: str) -> bool:
        with self._lock:
            return url in self._urls

    def done_urls(self) -> set:
        with self._lock:
            return set(self._urls)

    # ---------- CSV 写入 ----------

    def _load_existing(self) -> None:
        """启动时加载已保存的行，避免重复写入。"""
        if not self.csv_path.exists():
            return
        try:
            with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != CSV_FIELDS:
                    return
                self._rows = [row for row in reader if any(row.values())]
        except Exception:
            self._rows = []

    def append(self, record: ArticleRecord) -> None:
        """追加一篇文章并立即持久化（先写临时文件再原子替换）。"""
        with self._lock:
            self._rows.append(record.to_csv_row())
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        with open(self.tmp_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(self._rows)
            f.flush()
            os.fsync(f.fileno())
        shutil.move(str(self.tmp_path), str(self.csv_path))

    def read_all(self) -> List[dict]:
        """读取当前完整 CSV（内存缓存与磁盘一致）。"""
        with self._lock:
            return [dict(row) for row in self._rows]

    def count(self) -> int:
        with self._lock:
            return len(self._rows)
