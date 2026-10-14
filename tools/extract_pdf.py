# -*- coding: utf-8 -*-
"""
PDF → 分章 markdown 提取器（法学教材/习题册）

用法：
  python tools/extract_pdf.py detect              # 打印结构信息
  python tools/extract_pdf.py extract             # 全部提取
  python tools/extract_pdf.py extract --only 教材 # 只提取教材
  python tools/extract_pdf.py extract --only 习题 # 只提取习题

教材策略（书签损坏，用版面扫描）：
  - 章起始页 = 「第X章」行且标题行 y 坐标 > 100（页眉为 y≈60-70）
  - 正文裁剪：保留 y ∈ [85, 745] 的文本行，去掉页眉页脚
习题册策略（书签完好）：
  - 按 TOC 切分；「参考答案」之前的条目为题目，之后的为答案
  - 题目与答案按单元标题配对，输出 题目.md 与 答案.md 分离（便于出题不泄底）
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Windows 控制台编码容错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz  # pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF_SEARCH_DIRS = [
    ROOT / "material" / "pdf",
    Path("D:/法学/民商法/《民法总论》-杨代雄"),
    Path("D:/法学/民商法"),
]
OUT_TEXTBOOK = ROOT / "kb" / "民法总论" / "教材"
OUT_EXERCISES = ROOT / "kb" / "民法总论" / "习题"
INDEX_OUT = ROOT / "kb" / "民法总论" / "README.md"

CH_LINE_RE = re.compile(r"^第[一二三四五六七八九十百]+章\s*.{0,40}$")
PAGE_NO_RE = re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$")

# ────────────────────────────── 通用工具 ──────────────────────────────


def find_pdfs():
    """在多处候选目录中查找教材与习题 PDF。"""
    pdfs = []
    for d in PDF_SEARCH_DIRS:
        if d.is_dir():
            pdfs.extend(p for p in d.glob("*.pdf") if not p.name.startswith("~"))
    uniq = {p.name: p for p in pdfs}
    textbook = exercises = None
    for name, p in uniq.items():
        if "习题" in name or "题库" in name:
            exercises = p
        elif "民法总论" in name and "笔记" not in name:
            textbook = p
    if textbook is None:
        cand = [p for p in uniq.values() if p not in (exercises,)]
        if len(cand) == 1:
            textbook = cand[0]
    return textbook, exercises


def safe_name(title, maxlen=50):
    s = re.sub(r'[\\/:*?"<>|]', " ", title).strip()
    return re.sub(r"\s+", " ", s)[:maxlen] or "未命名"


def get_page_lines(page, ymin=0, ymax=900):
    """取页内文本行（可选 y 裁剪），返回 [(y0, text), ...] 按阅读顺序。"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            y0 = l["bbox"][1]
            if not (ymin <= y0 <= ymax):
                continue
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if txt:
                out.append((y0, txt))
    out.sort(key=lambda t: (round(t[0] / 5), t[0]))  # 行聚合排序
    return [t for _, t in out]


def is_heading(t):
    t = t.strip()
    if not t or len(t) > 40:
        return False
    return bool(
        re.match(r"^第[一二三四五六七八九十百零〇\d]+[章节讲]\s*\S", t)
        or re.match(r"^第[一二三四五六七八九十百零〇\d]+节\s*\S", t)
        or re.match(r"^\d+[\.、]\s*\S", t)
    )


def para_join(text):
    """段落内断行接回；标题行独立；句末标点收段。"""
    out, buf = [], []
    for line in text.splitlines():
        s = line.rstrip()
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
    return "\n".join(out)


# ────────────────────────────── 教材：版面扫描策略 ──────────────────────────────

# 章名映射（依据习题册单元标题，扫描只能识别「第X章」）
CHAPTER_NAMES = {
    "第一章": "民法概念论",
    "第二章": "民法体系论",
    "第三章": "民法方法论",
    "第四章": "自然人",
    "第五章": "法人",
    "第六章": "非法人组织",
    "第七章": "物和其他权利客体",
    "第八章": "权利变动概述",
    "第九章": "法律行为与意思表示的一般原理",
    "第十章": "法律行为的成立与生效",
    "第十一章": "法律行为的效力障碍",
    "第十二章": "法律行为的归属",
    "第十三章": "权利救济",
    "第十四章": "权利的时间维度",
    "第十五章": "期间与期日",
}


def scan_chapter_starts(doc):
    """扫描章起始页。返回 [(title, page0), ...]（page0 为 0-based）。"""
    starts = {}
    for i in range(doc.page_count):
        for b in doc[i].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                y0 = l["bbox"][1]
                txt = "".join(s["text"] for s in l["spans"]).strip()
                m = re.match(r"^(第[一二三四五六七八九十百]+章)(.{0,40})$", txt)
                if m and y0 > 100 and y0 < 400 and len(txt) < 45:
                    # 目录页（页码 < 20）跳过
                    if i >= 20:
                        name = CHAPTER_NAMES.get(m.group(1))
                        title = f"{m.group(1)} {name}".strip() if name else txt
                        starts.setdefault(i, title)
    return [(t, p) for p, t in sorted(starts.items())]


def extract_textbook(pdf_path, out_dir):
    doc = fitz.open(pdf_path)
    starts = scan_chapter_starts(doc)
    # 生成区间：每章到下一章起始页为止
    chapters = []
    for idx, (title, p0) in enumerate(starts):
        end = starts[idx + 1][1] - 1 if idx + 1 < len(starts) else doc.page_count - 1
        chapters.append((title, p0, end))

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"pdf": pdf_path.name, "pages": doc.page_count, "strategy": "heading-scan", "chapters": []}
    for idx, (title, start, end) in enumerate(chapters):
        parts = []
        for pno in range(start, end + 1):
            lines = get_page_lines(doc[pno], ymin=85, ymax=745)
            lines = [l for l in lines if not PAGE_NO_RE.match(l)]
            parts.append("\n".join(lines))
        body = para_join("\n\n".join(parts))
        fname = f"{idx + 1:02d}-{safe_name(title)}.md"
        (out_dir / fname).write_text(
            f"# {title}\n\n> 来源：{pdf_path.name} 第 {start + 1}–{end + 1} 页\n\n{body}\n",
            encoding="utf-8",
        )
        report["chapters"].append({"file": fname, "title": title, "pages": f"{start + 1}-{end + 1}"})
    doc.close()
    return report


# ────────────────────────────── 习题册：TOC 配对策略 ──────────────────────────────


def extract_exercises(pdf_path, out_dir):
    doc = fitz.open(pdf_path)
    toc = [(lv, t.strip(), pg) for lv, t, pg in doc.get_toc(simple=True)]
    # 找到「参考答案」位置
    ans_idx = next((i for i, (_, t, _) in enumerate(toc) if "参考答案" in t), None)
    q_entries = toc[:ans_idx] if ans_idx is not None else toc
    a_entries = toc[ans_idx:] if ans_idx is not None else []

    def norm(t):
        return re.sub(r"\s+", "", t)

    ans_by_title = {}
    for _, t, pg in a_entries:
        if "参考答案" in t:
            continue
        ans_by_title.setdefault(norm(t), []).append((t, pg - 1))

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"pdf": pdf_path.name, "pages": doc.page_count, "strategy": "toc-pairing", "chapters": []}

    def extract_pages(p0, p1, ymin=0):
        parts = []
        for pno in range(p0, p1 + 1):
            lines = [l for l in get_page_lines(doc[pno], ymin=ymin, ymax=900) if not PAGE_NO_RE.match(l)]
            parts.append("\n".join(lines))
        return para_join("\n\n".join(parts))

    for idx, (_, title, pg) in enumerate(q_entries):
        p0 = pg - 1
        p1 = (q_entries[idx + 1][2] - 2) if idx + 1 < len(q_entries) else (a_entries[0][2] - 2 if a_entries else doc.page_count - 1)
        body = extract_pages(p0, p1, ymin=45)
        fname = f"{idx + 1:02d}-{safe_name(title)}-题目.md"
        (out_dir / fname).write_text(
            f"# {title}（题目）\n\n> 来源：{pdf_path.name} 第 {p0 + 1}–{p1 + 1} 页\n\n{body}\n",
            encoding="utf-8",
        )
        entry = {"file": fname, "title": title, "pages": f"{p0 + 1}-{p1 + 1}"}

        ans = ans_by_title.get(norm(title), [])
        if ans:
            a_title, a_p0 = ans[0]
            # 答案区间：下一个答案条目起始页或文末
            pos = [i for i, (_, t, _) in enumerate(a_entries) if norm(t) == norm(title)]
            a_idx = pos[0]
            a_end = a_entries[a_idx + 1][2] - 2 if a_idx + 1 < len(a_entries) else doc.page_count - 1
            abody = extract_pages(a_p0, a_end, ymin=45)
            afname = f"{idx + 1:02d}-{safe_name(title)}-答案.md"
            (out_dir / afname).write_text(
                f"# {title}（参考答案）\n\n> 来源：{pdf_path.name} 第 {a_p0 + 1}–{a_end + 1} 页\n\n{abody}\n",
                encoding="utf-8",
            )
            entry["answer_file"] = afname
        report["chapters"].append(entry)
    doc.close()
    return report


# ────────────────────────────── 主流程 ──────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["detect", "extract"])
    ap.add_argument("--only", choices=["教材", "习题"])
    args = ap.parse_args()

    textbook, exercises = find_pdfs()
    if textbook is None:
        print("❌ 未找到教材 PDF。候选目录：material/pdf/ 与 D:/法学/民商法/《民法总论》-杨代雄/")
        sys.exit(1)

    if args.mode == "detect":
        for label, p in [("教材", textbook), ("习题", exercises)]:
            if p is None:
                print(f"{label}: 未找到\n")
                continue
            doc = fitz.open(p)
            toc = [(lv, t.strip(), pg) for lv, t, pg in doc.get_toc(simple=True)]
            print(f"=== {label} ===")
            print(f"  文件: {p}")
            print(f"  页数: {doc.page_count}")
            print(f"  书签目录: {len(toc)} 条")
            for lv, t, pg in toc[:45]:
                print(f"    {'  ' * (lv - 1)}{t}  → p.{pg}")
            doc.close()
            print()
        return

    reports = []
    targets = []
    if args.only != "习题":
        targets.append(("教材", textbook, extract_textbook, OUT_TEXTBOOK))
    if args.only != "教材" and exercises:
        targets.append(("习题", exercises, extract_exercises, OUT_EXERCISES))
    if not targets:
        print("❌ 没有可提取的文件")
        sys.exit(1)

    for kind, p, fn, out_dir in targets:
        print(f"提取 {kind}: {p.name} ...")
        reports.append(fn(p, out_dir))
        print(f"  ✅ {len(reports[-1]['chapters'])} 章 → {out_dir.relative_to(ROOT)}")

    # 索引
    lines = ["# 民法总论（杨代雄）— 知识库索引", ""]
    for r in reports:
        lines += [f"## {r['pdf']}", f"- 总页数：{r['pages']}，策略：{r['strategy']}", "", "| 文件 | 章节 | 页码 |", "|---|---|---|"]
        for c in r["chapters"]:
            ans = f"，答案见 {c['answer_file']}" if c.get("answer_file") else ""
            lines.append(f"| {c['file']} | {c['title']} | {c['pages']}{ans} |")
        lines.append("")
    lines += ["## 使用说明", "",
              "- 教材文件按章存放；教学时先读章首「来源」标注的页码区间，可回溯原 PDF。",
              "- 习题题目与答案分离：出 quiz 时只读「题目」文件，判分后核对「答案」文件。",
              "- 法条引用务必经 `law-verifier` 或 `kb/laws/` 核对。"]
    INDEX_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 索引: {INDEX_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
