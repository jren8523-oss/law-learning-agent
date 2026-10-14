# -*- coding: utf-8 -*-
"""从 OCR 的 out.txt 抽取指定页区间（用于读目录、定位章节边界）。
用法：
  python tools/ocr_dump.py <out.txt> --pages 1 20
"""
import argparse
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("txt")
    ap.add_argument("--pages", nargs=2, type=int, required=True, help="[start end] 含两端")
    args = ap.parse_args()

    t = open(args.txt, encoding="utf-8").read()
    pages = {}
    for m in re.finditer(r"===== PDF第(\d+)页 =====\n(.*?)(?=\n\n===== PDF第|\Z)", t, re.S):
        pages[int(m.group(1))] = m.group(2).rstrip()

    for p in range(args.pages[0], args.pages[1] + 1):
        if p in pages:
            print(f"\n----- PDF第{p}页 -----\n{pages[p]}")


if __name__ == "__main__":
    main()
