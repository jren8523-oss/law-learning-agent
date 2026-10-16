# -*- coding: utf-8 -*-
"""
法大考研民法重点热点背诵笔记：out.txt（带页标记）→ kb/法大考研民法背诵笔记/教材/*.md
按「编」切章；每个编的起止页做「标题裁剪」，保证内容不重不漏。
用法：python tools/import_fada_note.py
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BOOK = "法大考研民法重点热点背诵笔记"
SRC = "material/pdf/2.27法大考研民法重点热点背诵笔记.pdf"
TXT = "_tmp_ocr/法大考研民法背诵笔记/out.txt"
OUT = "kb/法大考研民法背诵笔记/教材"

# (起始页, 起始标题, 文件名)。封面目录单独处理。
# 每个编从「起始标题」所在的页开始，到下一个编的起始标题所在页为止。
BOUNDARIES = [
    (11, "第一编 民法总则编", "01-第一编 民法总则编.md"),
    (61, "第二编 物权编", "02-第二编 物权编.md"),
    (106, "第三编 债法总论", "03-第三编 债法总论.md"),
    (139, "第四编 合同", "04-第四编 合同.md"),
    (166, "第五编 自然人的人格权", "05-第五编 自然人的人格权.md"),
    (169, "第六编 婚姻家庭编与继承编", "06-第六编 婚姻家庭编与继承编.md"),
    (173, "第七编 侵权责任编", "07-第七编 侵权责任编.md"),
    (190, "民法热点知识部分", "08-民法热点知识部分.md"),
]
TOTAL_PAGES = 206


def load_pages(txt_path):
    t = Path(txt_path).read_text(encoding="utf-8")
    pages = {}
    for m in re.finditer(r"===== PDF第(\d+)页 =====\n(.*?)(?=\n\n===== PDF第|\Z)", t, re.S):
        pages[int(m.group(1))] = m.group(2).rstrip()
    return pages


def find_heading_line(page_text, heading):
    """返回标题所在行号（0-based），找不到返回 None。"""
    for i, ln in enumerate(page_text.splitlines()):
        if ln.strip().lstrip("#").strip() == heading:
            return i
    return None


def main():
    pages = load_pages(TXT)
    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)

    # 1) 封面与目录（PDF 1-10）
    body = []
    for p in range(1, 11):
        if p in pages and pages[p].strip():
            body.append(f"<!-- PDF第{p}页 -->\n\n{pages[p].strip()}")
    header = f"# {BOOK} · 封面与目录\n\n> 来源：{SRC}（PDF 第 1–10 页）\n\n---\n\n"
    (out / "00-封面与目录.md").write_text(header + "\n\n".join(body) + "\n", encoding="utf-8")
    print(f"✓ 00-封面与目录.md  PDF 1–10")

    # 2) 各编
    for i, (start, heading, fname) in enumerate(BOUNDARIES):
        end = BOUNDARIES[i + 1][0] if i + 1 < len(BOUNDARIES) else TOTAL_PAGES
        next_heading = BOUNDARIES[i + 1][1] if i + 1 < len(BOUNDARIES) else None

        parts = []
        for p in range(start, end + 1):
            if p not in pages or not pages[p].strip():
                continue
            txt = pages[p].strip()
            lines = txt.splitlines()
            # 起始页：裁掉起始标题之前的内容
            if p == start:
                idx = find_heading_line(txt, heading)
                if idx is not None:
                    txt = "\n".join(lines[idx:])
            # 结束页（若与下一编同页）：裁掉下一编标题之后的内容
            if p == end and next_heading is not None and end == start:
                # 单页编（理论上不会发生，此处兜底）
                idx = find_heading_line(txt, next_heading)
                if idx is not None:
                    txt = "\n".join(lines[:idx])
            elif p == end and next_heading is not None:
                idx = find_heading_line(txt, next_heading)
                if idx is not None:
                    txt = "\n".join(lines[:idx])
            if txt.strip():
                parts.append(f"<!-- PDF第{p}页 -->\n\n{txt}")

        title = heading
        header = f"# {BOOK} · {title}\n\n> 来源：{SRC}（PDF 第 {start}–{end} 页）\n\n---\n\n"
        (out / fname).write_text(header + "\n\n".join(parts) + "\n", encoding="utf-8")
        print(f"✓ {fname}  PDF {start}–{end}  （标题：{heading}）")

    print(f"✅ {BOOK} 切章完成（{len(BOUNDARIES) + 1} 文件）")


if __name__ == "__main__":
    main()
