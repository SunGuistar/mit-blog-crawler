"""共享配置：路径与采集常量。

所有路径均基于本文件所在位置解析，不依赖 IDE 工作目录。
"""

from pathlib import Path

# Crawler/ 项目根目录（backend/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
FRONTEND_DIR = BASE_DIR / "frontend"

PLAYWRIGHT_CSV = DATA_DIR / "playwright_results.csv"
DRISSIONPAGE_CSV = DATA_DIR / "drissionpage_results.csv"

BASE_URL = "https://mitadmissions.org"
BLOGS_URL = f"{BASE_URL}/blogs/"

# CSV 六个字段，名称与顺序不可修改
CSV_FIELDS = [
    "Title",
    "Author",
    "Comment Count",
    "Time",
    "Article Content",
    "Images In Article",
]

# 礼貌访问：请求间隔（秒）
REQUEST_DELAY = (1.0, 2.0)
# 单篇文章失败重试次数
MAX_RETRIES = 2
# 页面加载超时（毫秒）
PAGE_TIMEOUT = 30_000

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
