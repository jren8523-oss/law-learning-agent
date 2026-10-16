# -*- coding: utf-8 -*-
"""课件 PDF → 按页 markdown（页号锚点 ## pNN）。

用法:
    python pdf2md.py <课件.pdf> [输出.md]
不带输出路径时，生成 <同名>.md 放在同目录。
"""
import sys
from pathlib import Path

import fitz  # pymupdf

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def convert(src: Path, out: Path) -> None:
    doc = fitz.open(src)
    lines = [
        f"# {src.stem} · 逐页文本",
        "",
        f"> 源：`{src.name}`（{doc.page_count} 页）",
        "> 页号＝课件页码。文本为原样抽取，未清洗。",
        "",
    ]
    for i, page in enumerate(doc, start=1):
        lines += [f"## p{i}", "", page.get_text("text").strip(), ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{src.name}: {doc.page_count} 页 → {out}")

    empty = sum(1 for page in doc if not page.get_text("text").strip())
    if empty > doc.page_count * 0.5:
        print(f"⚠ 警告：{empty}/{doc.page_count} 页抽不出文字——这是扫描件/图片型 PDF，"
              "上面的稿子基本是空的，需要先 OCR，不要拿它去讲课。")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".md")
    convert(src, out)


if __name__ == "__main__":
    main()
