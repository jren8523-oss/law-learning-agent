# -*- coding: utf-8 -*-
"""
纯扫描版 PDF → PaddleOCR-VL 云 API（AI Studio）提取器（可断点续跑）

前置：先把 PDF 按每 N 页切成 chunk_<起>-<止>.pdf（用系统 python + fitz），
      块文件名必须含 "起-止" 页码（1-based 含两端），例如 chunk_0001-0010.pdf。

用法（用 paddleocr 的 venv python 跑）：
    $env:PADDLEOCR_ACCESS_TOKEN = "<token>"
    C:\\Users\\lenovo\\.paddleocr-mcp-venv\\Scripts\\python.exe tools/ocr_paddlecloud.py \
        --chunks _tmp_ocr/chunks --cache _tmp_ocr/cache.json --out _tmp_ocr/out.txt [--limit N]

- 逐块提交 AI Studio PaddleOCR-VL-1.6 云推理，每块返回每页 markdown。
- 结果按 chunk 名写入 JSON 缓存，中断重跑自动跳过已完成块（--limit 0 = 不限）。
- 输出 txt 带 `\n\n===== PDF第N页 =====\n\n` 页标记，供后续分章脚本再处理。
"""
import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from paddleocr._api_client.async_client import AsyncPaddleOCRClient
from paddleocr._api_client.models import Model, PaddleOCRVLOptions


def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(path: Path, cache: dict):
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def chunk_page_range(name: str):
    m = re.search(r"(\d+)-(\d+)", name)
    if not m:
        raise ValueError(f"chunk 文件名需含起止页码（如 chunk_0001-0010.pdf）: {name}")
    return int(m.group(1)), int(m.group(2))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理 N 块（0=不限）")
    ap.add_argument("--concurrency", type=int, default=4, help="并发提交块数")
    args = ap.parse_args()

    chunks_dir = Path(args.chunks)
    cache_path = Path(args.cache)
    out_path = Path(args.out)
    cache = load_cache(cache_path)

    chunk_files = sorted(chunks_dir.glob("chunk_*.pdf"), key=lambda p: p.name)
    if not chunk_files:
        print("未找到 chunk_*.pdf", flush=True)
        return

    token = os.environ.get("PADDLEOCR_ACCESS_TOKEN", "")
    if not token:
        print("❌ 缺少 PADDLEOCR_ACCESS_TOKEN", flush=True)
        return

    options = PaddleOCRVLOptions(use_chart_recognition=True, use_seal_recognition=True)
    sem = asyncio.Semaphore(max(1, args.concurrency))
    lock = asyncio.Lock()
    stats = {"done": 0}

    async def process(cf: Path):
        a, b = chunk_page_range(cf.name)
        print(f"→ OCR {cf.name} (第{a}–{b}页)...", flush=True)
        result = None
        last_err = None
        for attempt in range(1, 4):
            try:
                result = await client.parse_document(
                    model=Model.PADDLE_OCR_VL_16,
                    file_path=str(cf),
                    options=options,
                )
                break
            except Exception as e:
                last_err = e
                print(f"  ↻ {cf.name} 第 {attempt} 次失败：{type(e).__name__}: {e}，稍后重试", flush=True)
                await asyncio.sleep(5 * attempt)
        if result is None:
            raise last_err
        pages = [p.markdown_text for p in result.pages]
        if len(pages) != (b - a + 1):
            print(f"  ⚠ {cf.name} 返回 {len(pages)} 页，预期 {b - a + 1} 页", flush=True)
        async with lock:
            cache[cf.name] = pages
            with open(out_path, "a", encoding="utf-8") as f:
                for i, txt in enumerate(pages):
                    f.write(f"\n\n===== PDF第{a + i}页 =====\n\n{txt}\n")
            save_cache(cache_path, cache)
            stats["done"] += 1
            print(f"  ✓ {cf.name} 完成（累计 {len(cache)} 块）", flush=True)

    async def run_one(cf: Path):
        async with sem:
            try:
                await process(cf)
                return None
            except Exception as e:
                print(f"  ✗ {cf.name} 失败：{type(e).__name__}: {e}", flush=True)
                async with lock:
                    save_cache(cache_path, cache)
                return cf.name

    async with AsyncPaddleOCRClient(token=token, poll_timeout=900.0) as client:
        todo = []
        for cf in chunk_files:
            if args.limit and len(todo) >= args.limit:
                break
            if cf.name in cache:
                continue
            todo.append(cf)
        failed = [r for r in await asyncio.gather(*(run_one(cf) for cf in todo)) if r]

    if failed:
        print(f"⚠ 失败 {len(failed)} 块：{failed}", flush=True)
    print(f"✅ 处理完成，本次 {stats['done']} 块，缓存累计 {len(cache)} 块", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
