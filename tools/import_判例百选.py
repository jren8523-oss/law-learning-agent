# -*- coding: utf-8 -*-
"""
民法判例百选 入库脚本：把 ocr 输出 out.txt 按编切分成 kb/民法判例百选/教材/*.md
用法：
    python tools/import_判例百选.py
"""
import re
from pathlib import Path

SRC = Path("_tmp_ocr/out.txt")
OUT_DIR = Path("kb/民法判例百选/教材")
OUT_DIR.mkdir(parents=True, exist_ok=True)

t = SRC.read_text(encoding="utf-8")

# 拆成 {页码: 文本}
pages = {}
for m in re.finditer(r"===== PDF第(\d+)页 =====\n(.*?)(?=\n\n===== PDF第|\Z)", t, re.S):
    pages[int(m.group(1))] = m.group(2).rstrip()

def dump(name, title, a, b):
    body = []
    for p in range(a, b + 1):
        if p in pages:
            body.append(pages[p].strip())
    text = "\n\n".join(x for x in body if x)
    header = f"# 民法判例百选 · {title}\n\n> 来源：民法判例百选.pdf（PDF 第 {a}–{b} 页）\n\n---\n\n"
    (OUT_DIR / name).write_text(header + text + "\n", encoding="utf-8")
    print(f"✓ {name}: PDF {a}–{b}，{len(text)} 字")

dump("01-总则.md", "总则（案例 001–026）", 17, 146)
dump("02-物权.md", "物权（案例 027–050）", 147, 266)
dump("03-合同.md", "合同（案例 051–087）", 267, 450)
dump("04-侵权.md", "侵权（案例 088–100）", 451, 516)
print("✅ 分编完成")
