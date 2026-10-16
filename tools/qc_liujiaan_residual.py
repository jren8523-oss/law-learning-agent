# -*- coding: utf-8 -*-
"""质检 4：残留 OCR 错字/碎片统计（逐讲），用于判断还需不需要逐讲 LLM 重写"""
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_liujiaan as E  # noqa

rows = []
for f in sorted(E.OUT_DIR.glob("[0-9][0-9]-*.md")):
    t = f.read_text(encoding="utf-8")
    body_lines = [l for l in t.splitlines() if len(l) >= 10 and not l.startswith(("#", ">", "[", "|"))]
    low = [l for l in body_lines if E.coverage(l, 0) < 0.85]
    frag = [l for l in body_lines if l.count("　→　") >= 2 or l.endswith("课程及纸质版联系")]
    rows.append((f.name, len(body_lines), len(low), len(frag), low[:1]))
rows.sort(key=lambda r: -(r[2] + r[3]))
print(f"{'文件':<16}{'正文行':>6}{'低覆盖行':>8}{'碎片行':>7}  例")
for name, n, low, frag, ex in rows[:14]:
    print(f"{name:<16}{n:>6}{low:>8}{frag:>7}  {ex[0][:60] if ex else ''}")
tot_low = sum(r[2] for r in rows)
tot_lines = sum(r[1] for r in rows)
print(f"\n全库：正文行 {tot_lines}，低常用字覆盖率行 {tot_low}（{tot_low/tot_lines:.1%}）")
