# -*- coding: utf-8 -*-
"""
PDF 按每 N 页切块（供 tools/ocr_paddlecloud.py 使用）。

用法：
  python tools/chunk_pdf.py <pdf路径> --out <输出目录> [--size 10]

- 块文件命名：chunk_0001-0010.pdf（1-based 含两端），匹配 ocr_paddlecloud.py 的页码解析。
- 重复运行会覆盖同块，可直接重切。
"""
import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=10)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(args.pdf)
    n = doc.page_count
    total = 0
    for start in range(0, n, args.size):
        end = min(n, start + args.size)
        a, b = start + 1, end
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end - 1)
        name = f"chunk_{a:04d}-{b:04d}.pdf"
        sub.save(out / name)
        sub.close()
        total += 1
    doc.close()
    print(f"✅ 切出 {total} 块 → {out}（每块 {args.size} 页，总 {n} 页）", flush=True)


if __name__ == "__main__":
    main()
