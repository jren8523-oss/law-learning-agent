# -*- coding: utf-8 -*-
"""
民法物权（刘家安）文字版提取器（heading-scan，无书签）

新版 PDF（5.4MB，有文字层，376 页）结构：
  - 页眉 running header =「第X章 标题」+ 印刷页码（每页顶部）
  - 章起始页 = running header 首次变化的页（跳过目录 p.13-14）
  - 文字层有 \u3000 全角空格穿插（排版残留），清洗去除

用法：python tools/extract_wq.py
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz

ROOT = Path(__file__).resolve().parent.parent


def find_pdf() -> Path:
    """在 material/inbox、material/pdf 下找 民法物权*.pdf（PDF 位置可能变动）。"""
    for d in (Path("material/inbox"), Path("material/pdf")):
        hit = next(d.glob("民法物权*.pdf"), None)
        if hit:
            return hit
    raise FileNotFoundError("找不到 民法物权*.pdf（已查 material/inbox 与 material/pdf）")


PDF = find_pdf()
OUT = ROOT / "kb" / "民法物权-刘家安" / "教材"

PAGE_NO_RE = re.compile(r"^\d{1,3}$")
CH_RE = re.compile(r"^第[一二三四五六七八九十]+章")


def safe_filename(name: str) -> str:
    """Windows 非法文件名字符 → 安全替代。

    章标题「第二章物权的客体: 物」里的 ASCII 冒号会被 Windows 当成 NTFS
    数据流(ADS)分隔符，导致正文写进 ADS、磁盘上只留一个 0 字节空壳文件。
    这里把 `:` 换成合法的全角 `：`，其余非法字符删除。
    """
    name = name.replace(":", "：")
    name = re.sub(r'[<>\"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.replace("： ", "：")


def header_of(page):
    """取页顶部运行页眉（第X章标题）。"""
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            y0 = l["bbox"][1]
            if y0 > 70:
                continue
            txt = "".join(s["text"] for s in l["spans"]).replace("\u3000", "").replace(" ", "").strip()
            if CH_RE.match(txt):
                return txt
    return None


def clean(txt):
    txt = txt.replace("\u3000", "")
    # 去私用区装饰字符（如 PDF 目录点线 􀪋 等）
    txt = re.sub(r"[\ue000-\uf8ff\U000f0000-\U0010ffff]", "", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


def chapter_title(page):
    """章标题页的大标题（y≈92 的「第X章」+ y≈125 的章名，拼接）。"""
    parts = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            y0 = l["bbox"][1]
            if 80 <= y0 <= 160:
                txt = clean("".join(s["text"] for s in l["spans"]))
                if txt:
                    parts.append(txt)
    title = "".join(parts)
    return title if title and CH_RE.match(title) else None


def find_chapters(doc):
    """按章标题页（大标题 y≈92）切章，跳过目录（前 15 页）。"""
    starts = []
    for i in range(14, doc.page_count):
        t = chapter_title(doc[i])
        if t:
            starts.append((t, i))
    return starts


def para_join(lines):
    out, buf = [], []
    for s in lines:
        if not s:
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        buf.append(s)
        if re.search(r"[。！？”」』）)]$", s):
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def main():
    doc = fitz.open(PDF)
    chapters = find_chapters(doc)
    print(f"识别 {len(chapters)} 章：")
    for h, p in chapters:
        print(f"  {h}  → p.{p + 1}")
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for idx, (title, p0) in enumerate(chapters):
        p1 = (chapters[idx + 1][1] - 1) if idx + 1 < len(chapters) else doc.page_count - 1
        lines = []
        for pno in range(p0, p1 + 1):
            hdr = header_of(doc[pno])
            for b in doc[pno].get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    y0 = l["bbox"][1]
                    if y0 < 85:
                        continue  # 去页眉+页码
                    txt = clean("".join(s["text"] for s in l["spans"]))
                    if not txt or PAGE_NO_RE.match(txt):
                        continue
                    if txt == hdr:
                        continue
                    lines.append(txt)
        body = "\n\n".join(para_join(lines))
        fname = f"{idx + 1:02d}-{safe_filename(title)}.md"
        (OUT / fname).write_text(
            f"# {title}\n\n> 来源：{PDF.name} 第 {p0 + 1}–{p1 + 1} 页\n\n{body}\n",
            encoding="utf-8",
        )
        report.append((fname, title, p0, p1))
        print(f"  ✅ {fname}  ({p0 + 1}–{p1 + 1}，{len(body)} 字)")
    # README
    lines = [f"# 民法物权（刘家安）— 知识库索引", "",
             f"- 来源：{PDF.name}", "- 角色：对照（物权编）", "- 提取策略：页眉 heading-scan，按章切分", "",
             "| 文件 | 章节 | 页码 |", "|---|---|---|"]
    for fname, title, p0, p1 in report:
        lines.append(f"| {fname} | {title} | {p0 + 1}-{p1 + 1} |")
    lines += ["", "## 使用说明", "",
              "- 本角色书不进判分链（判分只锚主线书习题册）。",
              "- 法条落地以大陆《民法典》为准（经 `kb/laws/` 或 law-verifier 核对）。"]
    (OUT.parent / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc.close()
    print(f"✅ 共 {len(report)} 章 → kb/民法物权-刘家安/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
