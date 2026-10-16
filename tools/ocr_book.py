# -*- coding: utf-8 -*-
"""
纯扫描版 PDF → OCR 文本提取器（可断点续跑）

用法：
  python tools/ocr_book.py <pdf路径> --cache <缓存json> --out <输出txt> [--pages A B]

- 对每一页：有文字层直接取文本；无文字层渲染 200DPI 图片 → rapidocr OCR。
- 结果逐页写入 JSON 缓存（page_index → 文本），中断后重跑自动跳过已缓存页。
- 输出 txt 带 `\n\n===== PDF第N页 =====\n\n` 页标记，供后续分章脚本再处理。

分块建议：`--pages 0 50` / `50 100` … 每块约 50 页（~8 分钟），跑完再跑下一块。
"""
import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz


def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(path: Path, cache: dict):
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", nargs=2, type=int, help="[start end) 0-based 半开区间")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    cache_path = Path(args.cache)
    out_path = Path(args.out)
    cache = load_cache(cache_path)
    # 输出文件追加模式：只写本次处理的新页
    existed = out_path.exists()

    p0, p1 = args.pages if args.pages else (0, doc.page_count)
    p0 = max(0, p0)
    p1 = min(doc.page_count, p1)

    ocr = None
    n_new = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for i in range(p0, p1):
            key = str(i)
            if key in cache:
                continue  # 已缓存（含之前跑过的）
            txt = doc[i].get_text().strip()
            if len(txt) >= 20:
                cache[key] = txt
            else:
                if ocr is None:
                    from rapidocr_onnxruntime import RapidOCR
                    ocr = RapidOCR()
                pix = doc[i].get_pixmap(dpi=200)
                result, _ = ocr(pix.tobytes("png"))
                txt = "\n".join(r[1] for r in result) if result else ""
                cache[key] = txt
            f.write(f"\n\n===== PDF第{i + 1}页 =====\n\n{txt}\n")
            n_new += 1
            if n_new % 5 == 0:
                save_cache(cache_path, cache)  # 每 5 页落一次盘
                print(f"  进度 {i + 1}/{p1}（本块新增 {n_new} 页）", flush=True)
    save_cache(cache_path, cache)
    doc.close()
    print(f"✅ 完成 {p0}–{p1}，新增 {n_new} 页 → {out_path}（缓存 {cache_path}，累计 {len(cache)} 页）")


if __name__ == "__main__":
    main()
