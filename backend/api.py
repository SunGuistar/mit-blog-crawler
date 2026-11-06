"""FastAPI 后端：REST API + SSE 实时进度 + 前端静态页面。"""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import (
    DRISSIONPAGE_CSV,
    FRONTEND_DIR,
    PLAYWRIGHT_CSV,
    CSV_FIELDS,
)
from .task_manager import manager

app = FastAPI(title="MIT Blog Crawler")

# 前端与后端同源部署，此配置仅为本地调试方便
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRequest(BaseModel):
    max_pages: int = 3  # 默认前 3 页；0 = 全部分页


# ---------- 任务控制 ----------

@app.post("/api/crawl/start")
def start_crawl(req: StartRequest):
    if req.max_pages < 0:
        raise HTTPException(400, "max_pages 不能为负数（0 表示全部分页）")
    try:
        task_ids = manager.start(req.max_pages)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"message": "two crawler tasks started", "tasks": task_ids}


@app.post("/api/crawl/stop")
def stop_crawl():
    manager.stop()
    return {"message": "stop signal sent to both tasks"}


@app.post("/api/crawl/reset")
def reset_crawl():
    """清空两套爬虫的全部采集数据（CSV + 断点文件），运行中禁止。"""
    if manager.is_running():
        raise HTTPException(409, "采集进行中，停止后才能重置")
    manager.reset()
    deleted = []
    for path in (PLAYWRIGHT_CSV, DRISSIONPAGE_CSV):
        for f in (path, path.with_name(path.name + ".tmp"), path.with_suffix(".urls.json")):
            if f.exists():
                f.unlink()
                deleted.append(f.name)
    return {"message": "已清空全部采集数据", "deleted": deleted}


@app.get("/api/crawl/status")
def crawl_status():
    return manager.status()


# ---------- SSE 实时进度（按框架独立推送，互不干扰） ----------

@app.get("/api/crawl/stream/{framework}")
async def crawl_stream(framework: str):
    if framework not in ("playwright", "drissionpage"):
        raise HTTPException(404, "framework 必须是 playwright 或 drissionpage")

    async def event_generator():
        while True:
            snap = manager.state(framework).snapshot()
            yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
            if snap["status"] in ("finished", "stopped", "error", "idle"):
                # 终态后再推一次，确保前端拿到最后状态
                await asyncio.sleep(0.5)
                snap = manager.state(framework).snapshot()
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------- 采集结果 ----------

CSV_BY_FRAMEWORK = {
    "playwright": PLAYWRIGHT_CSV,
    "drissionpage": DRISSIONPAGE_CSV,
}


def _read_csv(framework: str) -> list:
    path = CSV_BY_FRAMEWORK[framework]
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if any(row.values())]


@app.get("/api/crawl/results/{framework}")
def crawl_results(
    framework: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
):
    if framework not in CSV_BY_FRAMEWORK:
        raise HTTPException(404, "framework 必须是 playwright 或 drissionpage")
    rows = _read_csv(framework)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "framework": framework,
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": rows[start : start + page_size],
    }


@app.get("/api/crawl/download/{framework}")
def download_csv(framework: str):
    if framework not in CSV_BY_FRAMEWORK:
        raise HTTPException(404, "framework 必须是 playwright 或 drissionpage")
    if manager.is_running():  # 采集未停止前禁止下载，避免拿到不一致的数据
        raise HTTPException(409, "采集进行中，停止后才能下载")
    path = CSV_BY_FRAMEWORK[framework]
    if not path.exists():
        raise HTTPException(404, f"{framework} 的 CSV 尚未生成")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


# ---------- 前端静态页面 ----------

@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{filename}")
def static_files(filename: str):
    path = FRONTEND_DIR / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
