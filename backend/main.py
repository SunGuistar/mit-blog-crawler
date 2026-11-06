"""启动入口：uvicorn backend.main:app --port 8000
或 python -m backend.main
"""

import uvicorn

from .api import app  # noqa: F401  （注册路由）

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
