# MIT Blog Crawler — Playwright + DrissionPage 双框架爬虫

使用 **Python** 分别基于 **Playwright** 和 **DrissionPage** 两套独立框架，并行爬取
[MIT Admissions 博客](https://mitadmissions.org/blogs/)，并通过一个简单的 Web 页面
实时对比两套框架的采集表现。

点击一次「开始采集」，两套爬虫**同时启动、并行运行、互不依赖**：
各自维护进度状态、各自保存 CSV、各自提供下载入口。

## 技术栈

- Python 3.10+
- FastAPI + Uvicorn（后端 API 与 SSE 实时推送）
- Playwright（Chromium，无头模式）
- DrissionPage（系统 Chrome，无头模式）
- BeautifulSoup4（页面解析）
- 前端：原生 HTML + CSS + JavaScript（无第三方框架）

## 项目目录结构

```text
Crawler/
├── backend/
│   ├── __init__.py
│   ├── main.py                  # 启动入口
│   ├── api.py                   # FastAPI 路由：REST + SSE + 静态页面
│   ├── task_manager.py          # 双任务并行调度与状态管理
│   ├── base_crawler.py          # 共享采集主流程（列表/分页/详情/重试/断点）
│   ├── playwright_crawler.py    # Playwright 爬虫（仅实现浏览器原语）
│   ├── drissionpage_crawler.py  # DrissionPage 爬虫（仅实现浏览器原语）
│   ├── parser.py                # 列表页/详情页字段提取
│   ├── csv_exporter.py          # 增量 CSV 写入（UTF-8 BOM + 原子替换）
│   ├── validator.py             # 数据质量校验与双框架对比
│   ├── models.py                # 数据模型与任务状态
│   └── config.py                # 路径与采集常量
├── frontend/
│   ├── index.html               # MIT Blog Crawler 页面
│   ├── style.css
│   └── app.js                   # 启动/停止、SSE、双卡片进度、独立预览分页
├── data/                        # 运行生成：两套 CSV 与断点文件
├── logs/                        # 运行生成：双框架日志、校验报告
├── tests/
│   ├── fixtures/                # 真实页面快照（离线测试用）
│   └── test_parser.py           # 解析器单元测试（不访问网络）
├── requirements.txt
└── README.md
```

## 环境配置

- Python 3.10 及以上（开发使用 3.12）
- Windows / macOS / Linux 均可；Windows 下路径自动适配
- 建议网络可访问 mitadmissions.org

## 依赖安装

```bash
cd Crawler
pip install -r requirements.txt
```

## 浏览器安装及配置

**Playwright**（自带 Chromium，推荐）：

```bash
python -m playwright install chromium
```

若下载失败或机器上已有 Chrome，代码会自动回退使用系统 Chrome（`channel="chrome"`），无需额外配置。

**DrissionPage**：默认自动查找系统已安装的 Chrome / Edge，无需手动下载浏览器。
无头模式由代码启用（`ChromiumOptions().headless(True)`）。

## 后端启动方式

```bash
cd Crawler
python -m backend.main
# 或
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## 前端访问地址

浏览器打开：

```text
http://127.0.0.1:8000/
```

## 如何启动双框架采集

1. 在「采集范围」中选择 **前 N 页**（默认 3 页）或 **全部分页**。
2. 点击 **开始采集**。
3. 后端一次性创建并启动 Playwright 与 DrissionPage 两个独立后台任务，
   页面两张进度卡片分别实时更新；**不提供单框架选择，两套始终同时运行**。
4. 点击 **停止采集** 向两个任务分别发送协作式停止信号，任务完成当前文章收尾后
   保存数据并释放浏览器。
5. **采集进行中禁止下载 CSV**，停止（或任务结束）后才可下载。

## 如何查看实时进度

- 页面两张卡片分别展示各框架的：运行状态、当前分页/总分页、已发现文章数、
  成功/失败数量、当前文章标题、进度条、开始时间与运行时长。
- 实时数据来自后端 SSE 接口：
  - `GET /api/crawl/stream/playwright`
  - `GET /api/crawl/stream/drissionpage`
- 文章总数未知时不显示伪造的百分比，只显示已处理数量。

## 两个 CSV 的下载方式

- 页面每张卡片上的下载按钮：
  - `下载 Playwright CSV` → `data/playwright_results.csv`
  - `下载 DrissionPage CSV` → `data/drissionpage_results.csv`
- 或直接访问：
  - `GET /api/crawl/download/playwright`
  - `GET /api/crawl/download/drissionpage`

CSV 为 **UTF-8 with BOM**，Windows Excel 直接打开不乱码；仅含题目规定的六个字段：
`Title, Author, Comment Count, Time, Article Content, Images In Article`。

## 如何进行数据质量验证

采集完成后运行：

```bash
cd Crawler
python -m backend.validator
```

输出两套 CSV 的独立检查报告（字段顺序、重复文章、空标题/作者、时间格式、
正文完整性、图片 URL 格式、评论数异常值等）及双框架横向对比，
报告同时保存到 `logs/validation_report.json`。

## 断点续爬方式

- 每完成一篇文章，URL 会写入 `data/<框架>.urls.json`，CSV 同步原子更新。
- 再次点击「开始采集」时自动跳过已采集文章，从断点继续；
- 停止任务后已保存的数据不会丢失，重启后继续采集即可。
- 如需从头重新采集，删除对应的 `data/playwright_results.csv`、
  `data/drissionpage_results.csv` 和 `*.urls.json` 即可。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/crawl/start` | body: `{"max_pages": 1}`（0=全部），同时启动两套任务 |
| POST | `/api/crawl/stop` | 协作式停止两套任务 |
| GET | `/api/crawl/status` | 两套任务的完整状态 |
| GET | `/api/crawl/stream/{fw}` | SSE 实时进度（fw = playwright / drissionpage） |
| GET | `/api/crawl/results/{fw}` | 分页查询结果 `?page=1&page_size=10` |
| GET | `/api/crawl/download/{fw}` | 下载对应 CSV |

## 已知问题和限制

1. **评论数量**：本站评论由 Disqus 托管。代码优先解析页面中的 Disqus identifier
   并尝试调用 Disqus 计数接口；当前运行环境访问 disqus.com 超时，
   接口不可达时 Comment Count 按需求默认为 **0**（获取失败原因记录于日志）。
   网络可达 Disqus 的环境下会自动填出真实数量。
2. **正文图片**：文章正文图片使用 flickity 懒加载（`data-flickity-lazyload-src`），
   解析器已按 `data-flickity-lazyload-src > data-src > src > srcset` 优先级取真实地址；
   少数图片若在采集时仍未加载出真实地址，可能漏采。
3. **访问频率**：默认每请求间隔 1~2 秒并带 2 次重试，全量采集（约 490+ 页、
   近 8000 篇文章）两套并行预计需要数小时，请合理安排。
4. **停止粒度**：协作式停止在"文章之间"检查信号，正在采集的文章会完整收尾。
5. 两套爬虫共享解析/清洗/CSV/校验模块，但浏览器实例、任务状态与 CSV 完全独立。
