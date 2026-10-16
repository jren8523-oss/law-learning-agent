# -*- coding: utf-8 -*-
"""
通用教材提取器（TOC 书签驱动）→ kb/<书名>/教材/NN-第X章.md + README.md

用法：
  python tools/extract_book.py detect "<pdf路径>"                 # 只打印书签结构
  python tools/extract_book.py extract "<pdf路径>" --title <书名> --dir <kb目录名> [--role 角色]

策略：
  - 书签 level-1 匹配「第X章 / 第X编 / 第X讲」为章；level-2「第X节」记入 README 映射
  - 章区间 = 本章起始页 → 下一章起始页-1；末章到「索引/后记/附录/主要参考」等 back-matter 之前
  - 版面：去页眉页脚、去页码、去水印广告（加微信…等）、段落接回
  - 正文里出现的「第X节」行转 ## 标题
"""
import argparse
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

PAGE_NO_RE = re.compile(r"^[\s·•\-–—]*\d{1,4}[\s·•\-–—]*$")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零〇]+[章编讲](?:\s*.{0,30})?$")
SECTION_RE = re.compile(r"^第[一二三四五六七八九十百零〇]+节(?:\s*.{0,30})?$")
BACKMATTER_RE = re.compile(r"^(词语索引|法条索引|条文索引|案例索引|后记|附录|主要参考|参考文献|名词索引)")
FRONTMATTER_RE = re.compile(r"^(封面|书名|版权|序|自序|前言|简目录|详目录|目录|出版说明)")

# 水印/广告噪声（含书签里混进的「加微信asxiao90」一类）
NOISE_PAT = [
    r"加微信\S*", r"微信\s*[:：]?\s*\S{0,20}", r"QQ\s*[:：]?\s*\d+", r"公众号\S*",
    r"二维码", r"asxiao\d*", r"vx\s*\d+", r"免费获取", r"更多资源", r"扫描二维码",
    r"本章要点",  # 有时是页眉装饰，误伤风险低
]
NOISE_RE = [re.compile(p) for p in NOISE_PAT]
WATERMARK_LINE_RE = re.compile(r"^(加微信|微信|QQ|公众号|asxiao|vx|扫描|更多|免费)[^\u4e00-\u9fff]{0,4}[\w@:：\-]{1,20}$")


def get_page_lines(page, ymin=70, ymax=760):
    """页内文本行，按阅读顺序。返回 [(y0, text, x0)]。"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            y0 = l["bbox"][1]
            if not (ymin <= y0 <= ymax):
                continue
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if txt:
                out.append((y0, txt, l["bbox"][0]))
    out.sort(key=lambda t: (round(t[0] / 5), t[1]))
    return out


def clean_line(txt):
    """去一行里的水印/广告残渣。"""
    for r in NOISE_RE:
        txt = r.sub("", txt)
    return re.sub(r"\s+", " ", txt).strip()


def is_heading(t):
    t = t.strip()
    return bool(
        re.match(r"^第[一二三四五六七八九十百零〇\d]+[章节讲]\s*\S", t)
        or re.match(r"^第[一二三四五六七八九十百零〇\d]+节\s*\S", t)
        or re.match(r"^[一二三四五六七八九十]+、", t)
        or re.match(r"^（[一二三四五六七八九十]+）", t)
    )


def para_join(lines):
    """段落接回；标题行独立；句末标点收段。"""
    out, buf = [], []
    for s in lines:
        if not s.strip():
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        if is_heading(s):
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(s)
            continue
        buf.append(s)
        if re.search(r"[。！？”」』）)]$", s):
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def extract_chapter_text(doc, p0, p1):
    """抽取 p0..p1（0-based，含）页正文，去页眉页脚页码，段落接回。"""
    raw_lines = []
    for pno in range(p0, p1 + 1):
        for _y, txt, x0 in get_page_lines(doc[pno]):
            if PAGE_NO_RE.match(txt):
                continue
            if WATERMARK_LINE_RE.match(txt):
                continue
            txt = clean_line(txt)
            if txt:
                raw_lines.append(txt)
    return para_join(raw_lines)


def get_toc(doc):
    """书签 → [(lv, title, page0)]，page0 为 0-based，page<0 记为 None。"""
    out = []
    for lv, t, pg in doc.get_toc(simple=True):
        out.append((lv, t.strip(), pg - 1 if pg > 0 else None))
    return out


def split_chapters(doc):
    """从书签识别章边界。返回 [(章标题, 起始页0, 结束页0)]。"""
    toc = get_toc(doc)
    chapters = []
    for lv, t, p0 in toc:
        t = re.sub(r"加微信\S*", "", t).strip()
        if lv == 1 and CHAPTER_RE.match(t) and p0 is not None:
            chapters.append([t, p0, None])
    # back-matter 起点：level-1 且匹配索引/后记等
    back_start = None
    for lv, t, p0 in toc:
        if lv == 1 and BACKMATTER_RE.match(t.strip()) and p0 is not None:
            back_start = p0
            break
    end_limit = back_start if back_start is not None else doc.page_count
    for i, ch in enumerate(chapters):
        ch[2] = (chapters[i + 1][1] - 1) if i + 1 < len(chapters) else end_limit - 1
    return chapters


def build_readme(pdf_name, title, role, chapters, out_dir):
    lines = [f"# {title} — 知识库索引", ""]
    lines += [f"- 来源：{pdf_name}", f"- 角色：{role}", "- 提取策略：TOC 书签驱动，按章切分", ""]
    lines += ["| 文件 | 章节 | 页码 |", "|---|---|---|"]
    for fname, ctitle, p0, p1 in chapters:
        lines.append(f"| {fname} | {ctitle} | {p0 + 1}-{p1 + 1} |")
    lines += ["", "## 使用说明", "",
              "- 教学/检索时先读章首「来源」标注的页码区间，可回溯原 PDF。",
              "- 本角色书不进判分链（判分只锚主线书习题册）。"]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract(pdf_path, title, dirname, role):
    doc = fitz.open(pdf_path)
    chapters = split_chapters(doc)
    if not chapters:
        print("❌ 未识别到章节书签")
        doc.close()
        return 1
    out_dir = ROOT / "kb" / dirname / "教材"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for idx, (ctitle, p0, p1) in enumerate(chapters):
        body = extract_chapter_text(doc, p0, p1)
        # 正文内「第X节」行 → ## 标题
        body_lines = []
        for ln in body:
            if SECTION_RE.match(ln.strip()):
                body_lines.append(f"\n## {ln.strip()}\n")
            else:
                body_lines.append(ln)
        body = "\n\n".join(x.strip() for x in "\n".join(body_lines).split("\n\n") if x.strip())
        fname = f"{idx + 1:02d}-{re.sub(r'[\\/:*?\"<>|]', '', ctitle).strip()}.md"
        (out_dir / fname).write_text(
            f"# {ctitle}\n\n> 来源：{Path(pdf_path).name} 第 {p0 + 1}–{p1 + 1} 页\n\n{body}\n",
            encoding="utf-8",
        )
        report.append((fname, ctitle, p0, p1))
        print(f"  ✅ {fname}  ({p0 + 1}–{p1 + 1}，{len(body)} 字)")
    build_readme(Path(pdf_path).name, title, role, report, out_dir)
    doc.close()
    print(f"✅ 共 {len(report)} 章 → kb/{dirname}/教材/")
    return 0


def detect(pdf_path):
    doc = fitz.open(pdf_path)
    toc = get_toc(doc)
    print(f"页数 {doc.page_count}，书签 {len(toc)} 条")
    for lv, t, p0 in toc:
        mark = "" if p0 is not None else "  ⚠️无页码"
        print(f"  {'  ' * (lv - 1)}[{p0 + 1 if p0 is not None else '?'}] {t}{mark}")
    doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["detect", "extract"])
    ap.add_argument("pdf")
    ap.add_argument("--title")
    ap.add_argument("--dir")
    ap.add_argument("--role", default="对照")
    args = ap.parse_args()
    if args.mode == "detect":
        detect(args.pdf)
        return 0
    if not args.title or not args.dir:
        print("extract 需要 --title 与 --dir")
        return 2
    return extract(args.pdf, args.title, args.dir, args.role)


if __name__ == "__main__":
    sys.exit(main())
