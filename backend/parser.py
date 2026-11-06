"""HTML 解析模块：列表页与详情页字段提取。

选择器基于对 mitadmissions.org/blogs/ 的实际页面结构分析：
- 列表文章卡片: article.tease--post 内 a.post-tease__h__link
- 分页: /blogs/page/N/，无 rel="next" 链接即为最后一页
- 详情标题: h1.page-topper__title（剔除内嵌作者 span）
- 作者: h1 .page-topper__title__name
- 时间: time.page-topper__date 的 datetime 属性（备用 JSON-LD datePublished）
- 正文: div.article__body
- 正文图片: 优先 data-flickity-lazyload-src（本站使用 flickity 懒加载）
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import ArticleRecord

BODY_TEXT_TAGS = ("p", "li", "blockquote", "h2", "h3", "h4", "figcaption")


def parse_list_page(html: str, page_url: str) -> Tuple[List[str], Optional[str]]:
    """解析列表页，返回 (文章 URL 列表, 下一页 URL 或 None)。"""
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    for article in soup.select("article.tease--post"):
        link = article.select_one("a.post-tease__h__link")
        if link and link.get("href"):
            urls.append(urljoin(page_url, link["href"]))

    next_url: Optional[str] = None
    next_link = soup.find(attrs={"rel": "next"})  # <a rel="next"> 或 <link rel="next">
    if next_link and next_link.get("href"):
        next_url = urljoin(page_url, next_link["href"])
    return urls, next_url


def _extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1.page-topper__title")
    if not h1:
        return ""
    parts = [text for text in h1.find_all(string=True, recursive=False)]
    if not parts:
        # 标题文本可能被包裹在 span 中，剔除作者/日期等附加节点后取余下文本
        for junk in h1.select("a, span.page-topper__title__name, time"):
            junk.decompose()
        return h1.get_text(" ", strip=True)
    return " ".join(p.strip() for p in parts if p.strip())


def _extract_author(soup: BeautifulSoup) -> str:
    name = soup.select_one("h1.page-topper__title .page-topper__title__name")
    if name:
        text = name.get_text(" ", strip=True)
        return re.sub(r"^by\s+", "", text).strip()
    return ""


def _extract_time(soup: BeautifulSoup) -> str:
    time_tag = soup.select_one("time.page-topper__date")
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"][:10]  # 2026-11-02T00:00:00-05:00 -> 2026-11-02
    # 备用：JSON-LD datePublished
    m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', soup.get_text(" ", strip=True))
    if not m:
        for script in soup.find_all("script", type="application/ld+json"):
            m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', script.get_text(" ", strip=True))
            if m:
                break
    return m.group(1) if m else ""


def _extract_content(soup: BeautifulSoup) -> Tuple[str, str]:
    """返回 (正文纯文本, 图片URL串)。保留段落换行，排除非正文区域。"""
    body = soup.select_one("div.article__body")
    if not body:
        return "", ""

    lines: List[str] = []
    seen = set()
    for tag in body.find_all(BODY_TEXT_TAGS):
        if tag.find_parent("blockquote") is not None and tag.name != "blockquote":
            continue  # blockquote 内部文本由 blockquote 自身统一提取
        text = tag.get_text(" ", strip=True)
        if text and text not in seen:
            seen.add(text)
            lines.append(text)

    image_urls: List[str] = []
    for img in body.find_all("img"):
        src = (
            img.get("data-flickity-lazyload-src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("src")
        )
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].strip().split(" ")[0]
        if not src:
            continue
        src = urljoin("https://mitadmissions.org", src)
        if src not in image_urls:
            image_urls.append(src)

    return "\n".join(lines), " | ".join(image_urls)


def extract_disqus_identifier(soup: BeautifulSoup, html: str) -> Optional[str]:
    """从详情页提取 Disqus identifier，供评论数接口使用。"""
    m = re.search(r"page\.identifier\s*=\s*'([^']+)'", html)
    if m:
        return m.group(1)
    for script in soup.find_all("script"):
        if script.string and "identifier" in script.string:
            m = re.search(r"identifier\s*[:=]\s*['\"]([^'\"]+)['\"]", script.string)
            if m:
                return m.group(1)
    return None


def parse_detail_page(html: str, url: str) -> ArticleRecord:
    """解析文章详情页，返回六字段记录（Comment Count 由爬虫另行获取）。"""
    soup = BeautifulSoup(html, "html.parser")
    content, images = _extract_content(soup)
    record = ArticleRecord(
        title=_extract_title(soup),
        author=_extract_author(soup),
        publish_time=_extract_time(soup),
        content=content,
        images=images,
        url=url,
    )
    record._disqus_identifier = extract_disqus_identifier(soup, html)  # type: ignore[attr-defined]
    return record
