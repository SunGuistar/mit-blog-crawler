"""数据质量校验：分别校验两套 CSV，并输出独立报告。

检查项：
1. 六字段名称与顺序
2. 重复文章
3. 标题为空
4. 作者为空
5. 时间格式 YYYY-MM-DD
6. 正文为空或过短（可能不完整）
7. 图片 URL 格式
8. 评论数异常值
9. 两套爬虫发现文章数量对比
10. 相同文章字段一致性对比

注意：评论数为空、图片为空 不视为失败（可能是真实空值），单独统计说明。
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from .config import CSV_FIELDS, DRISSIONPAGE_CSV, PLAYWRIGHT_CSV, LOGS_DIR

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://\S+$")
CONTENT_MIN_LEN = 50  # 正文少于该长度视为"明显不完整"（短图文帖除外，仅警告）


def validate_csv(path: Path) -> dict:
    report = {
        "file": str(path),
        "exists": path.exists(),
        "total_rows": 0,
        "checks": {},
    }
    if not path.exists():
        report["checks"]["file_exists"] = "FAIL：CSV 不存在"
        return report

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        report["checks"]["header"] = (
            "PASS" if reader.fieldnames == CSV_FIELDS
            else f"FAIL：字段或顺序不符 -> {reader.fieldnames}"
        )
        rows = [row for row in reader if any(row.values())]

    report["total_rows"] = len(rows)

    titles = [r["Title"].strip() for r in rows]
    report["checks"]["duplicate_titles"] = (
        f"WARN：发现 {len(titles) - len(set(titles))} 条重复标题"
        if len(titles) != len(set(titles)) else "PASS（无重复）"
    )
    report["checks"]["empty_title"] = _count(rows, lambda r: not r["Title"].strip())
    report["checks"]["empty_author"] = _count(rows, lambda r: not r["Author"].strip())
    report["checks"]["bad_time_format"] = _count(
        rows, lambda r: not DATE_RE.match(r["Time"].strip())
    )
    report["checks"]["short_content"] = _count(
        rows, lambda r: 0 < len(r["Article Content"].strip()) < CONTENT_MIN_LEN
    )
    report["checks"]["empty_content"] = _count(
        rows, lambda r: not r["Article Content"].strip()
    )
    report["checks"]["bad_image_url"] = _count(rows, _bad_image_cell)
    report["checks"]["suspicious_comment_count"] = _count(rows, _bad_comment_cell)

    empty_comments = sum(1 for r in rows if not r["Comment Count"].strip())
    empty_images = sum(1 for r in rows if not r["Images In Article"].strip())
    report["notes"] = {
        "empty_comment_count": f"{empty_comments} 条为空（可能是 Disqus 不可达，未获取，不是伪造）",
        "empty_images": f"{empty_images} 条为空（可能正文确实无图，属正常）",
    }
    return report


def _count(rows, pred) -> str:
    n = sum(1 for r in rows if pred(r))
    return f"PASS（0 条）" if n == 0 else f"WARN：{n} 条"


def _bad_image_cell(row: dict) -> bool:
    cell = row["Images In Article"].strip()
    if not cell:
        return False  # 无图是合法空值
    return any(not URL_RE.match(u.strip()) for u in cell.split(" | "))


def _bad_comment_cell(row: dict) -> bool:
    cell = row["Comment Count"].strip()
    if not cell:
        return False  # 空值合法（未获取或无评论无法区分时置空）
    return not cell.isdigit()


def compare_frameworks(report_a: dict, report_b: dict, name_a: str, name_b: str) -> dict:
    """两套 CSV 的横向对比（发现数量 + 相同标题文章的字段一致性）。"""
    rows_a = _read_rows(Path(report_a["file"]))
    rows_b = _read_rows(Path(report_b["file"]))
    by_title_a = {r["Title"].strip(): r for r in rows_a if r["Title"].strip()}
    by_title_b = {r["Title"].strip(): r for r in rows_b if r["Title"].strip()}

    common = set(by_title_a) & set(by_title_b)
    diff = []
    for title in sorted(common):
        for field in CSV_FIELDS:
            if field == "Comment Count":
                continue  # 评论数受 Disqus 可达性影响，单独说明
            if by_title_a[title][field] != by_title_b[title][field]:
                diff.append({"title": title[:50], "field": field})

    return {
        f"{name_a}_articles": len(rows_a),
        f"{name_b}_articles": len(rows_b),
        "common_titles": len(common),
        "field_mismatches_excluding_comment": diff,
    }


def _read_rows(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any(r.values())]


def run_validation() -> dict:
    rp = validate_csv(PLAYWRIGHT_CSV)
    rd = validate_csv(DRISSIONPAGE_CSV)
    comparison = compare_frameworks(rp, rd, "playwright", "drissionpage")
    summary = {"playwright": rp, "drissionpage": rd, "comparison": comparison}

    out = LOGS_DIR / "validation_report.json"
    import json

    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _print_report(summary: dict) -> None:
    for fw in ("playwright", "drissionpage"):
        rep = summary[fw]
        print(f"\n===== {fw} =====")
        print(f"文件: {rep['file']}  行数: {rep['total_rows']}")
        for k, v in rep["checks"].items():
            print(f"  [{k}] {v}")
        for k, v in rep.get("notes", {}).items():
            print(f"  (说明) {k}: {v}")
    print("\n===== 双框架对比 =====")
    for k, v in summary["comparison"].items():
        print(f"  {k}: {v}")
    print(f"\n报告已保存: {LOGS_DIR / 'validation_report.json'}")


if __name__ == "__main__":
    _print_report(run_validation())
