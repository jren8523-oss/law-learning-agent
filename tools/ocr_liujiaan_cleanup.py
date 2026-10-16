# -*- coding: utf-8 -*-
"""
清理 PaddleOCR-VL 输出的刘家安笔记 markdown，写回标准讲次格式。

用法：
  python tools/ocr_liujiaan_cleanup.py <ocr输入.md> <讲次号> [输出.md]
示例：
  python tools/ocr_liujiaan_cleanup.py "D:\\临时\\24【笔记】...by_PaddleOCR-VL-1.6.md" 24
输出：
  kb/参考讲义/刘家安民法基础课/24-第24讲.md
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "kb" / "参考讲义" / "刘家安民法基础课"

HDR = "21法考内部课程必加Q群700368374"
FOOTER = "2020年刘家安 CCtalk 民法基础课课堂笔记"


def is_noise(l):
    t = l.strip()
    if not t:
        return True
    if HDR in t:
        return True
    if t == FOOTER:
        return True
    if "<img" in t or "pplines-online" in t:
        return True
    return False


def main():
    src = Path(sys.argv[1])
    num = int(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else OUT_DIR / f"{num:02d}-第{num}讲.md"

    lines = src.read_text(encoding="utf-8").splitlines()

    # 边界：页眉行（正文页）或广告标题行（广告页）
    bounds = []
    for i, l in enumerate(lines):
        if HDR in l:
            bounds.append((i, False))
        elif "招生简章" in l:
            bounds.append((i, True))
    bounds.sort()

    blocks = []
    for k, (start, is_ad) in enumerate(bounds):
        end = bounds[k + 1][0] if k + 1 < len(bounds) else len(lines)
        blocks.append((is_ad, lines[start:end]))

    valid = ad = 0
    body = []
    page_no = 0
    for is_ad, block in blocks:
        if is_ad:
            ad += 1
            continue
        cleaned = [l for l in block if not is_noise(l)]
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        if not cleaned:
            continue
        page_no += 1
        body.append(f"<!-- 原PDF第{page_no}页 -->")
        body.extend(cleaned)
        body.append("")
        valid += 1

    header = [
        f"# 刘家安民法基础课 第{num}讲",
        "",
        f"> 来源：{src.name}（{valid} 页有效内容，跳过 {ad} 页广告，PaddleOCR-VL 识别，页码为顺序号）",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(header + body).rstrip() + "\n", encoding="utf-8")
    print(f"valid={valid} ad={ad} blocks={len(blocks)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
