# -*- coding: utf-8 -*-
"""债法教材提取器（TOC 书签驱动，按「章」切分）

处理两本已带文字层的债法书：
  - 解亘/冯洁语/尚连杰《板书体债法总论》（北大 2024，6 部 22 章）
  - 王泽鉴《债法原理》（北大 2022 重排版，3 编 12 章）

书签层级：lvl1=部/编，lvl2=章，lvl3=节（lvl4 条目不成标题）。
文字层是 OCR 产物，本脚本只做**版面清洗**（去页眉/页码/标题残片、合并段落），
**不改动正文文字**（含错别字一律照旧），以免误伤。

用法：python tools/extract_zhaifa.py
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

BOOKS = [
    dict(pdf="material/inbox/板书体债法总论okocr.pdf",
         out="kb/债法总论-解亘/教材",
         readme="kb/债法总论-解亘/README.md",
         title="板书体债法总论（解亘、冯洁语、尚连杰）",
         role="**主线（债法骨架）**",
         running_titles=("板书体债法总论",)),
    dict(pdf="material/inbox/债法原理 王泽鉴 2022 OCR.pdf",
         out="kb/债法原理-王泽鉴/教材",
         readme="kb/债法原理-王泽鉴/README.md",
         title="债法原理（王泽鉴 2022 重排版）",
         role="对照（债总前半截 + 比较法）",
         running_titles=("债法原理",)),
]

NUMS = r"0-9一二三四五六七八九十"
CN = r"一二三四五六七八九十"
PART_RE = re.compile(rf"^(第[{NUMS}]+[部编])")
CHAP_RE = re.compile(rf"^(第[{NUMS}]+章)\s*(.*)$")

# ── 页眉/页码（只在每页前 4 行里判）──
PAGENO_RE = re.compile(r"^\s*\d{1,4}\s*$")
ROMAN_HEAD_RE = re.compile(r"^I\s*(?:\S{0,12})?\s*$")
RUNHEAD_RE = re.compile(rf"^第?\s*\d+\s*[部编]\s*[．.、]?\s*第\s*\d+\s*章")
SINGLE_DI_RE = re.compile(r"^[第笫]\s*$")
# ── 页首的 编/章/节 标题行 ──
HEAD_PARTCHAP_RE = re.compile(rf"^第\s*[{NUMS}lI]+\s*[编部章]")
HEAD_SEC_RE = re.compile(rf"^第?\s*[{NUMS}lIi]{{1,2}}\s*节\s*$")
# ── 条目行（自成一段）与句末 ──
ENTRY_RE = re.compile(r"^([一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\(\d+\)|（\d+）|\d+\s*[.．]\s*)")
SENT_END_RE = re.compile(r"[。！？：；”』）)]$")


def is_head(line: str, running_titles) -> bool:
    s = line.strip()
    if not s:
        return False
    if PAGENO_RE.match(s) or ROMAN_HEAD_RE.match(s):
        return True
    if RUNHEAD_RE.match(s) or SINGLE_DI_RE.match(s):
        return True
    if s in running_titles:
        return True
    return False


def clean_page(lines, strip_titles: bool, running_titles):
    """去页首页眉/页码；strip_titles 时再去掉开头的 编/章/节 标题行与短续行。"""
    kept = [l.rstrip() for l in lines]
    head_zone = min(4, len(kept))
    kept = [l for i, l in enumerate(kept) if not (i < head_zone and is_head(l, running_titles))]
    j = 0
    if strip_titles:
        prev_heading = False
        while j < len(kept):
            s = kept[j].strip()
            is_h = bool(HEAD_PARTCHAP_RE.match(s) or HEAD_SEC_RE.match(s) or SINGLE_DI_RE.match(s))
            is_cont = prev_heading and s and len(s) <= 24 and not SENT_END_RE.search(s) and not ENTRY_RE.match(s)
            if is_h or is_cont:
                prev_heading = True
                j += 1
                continue
            break
    return [l for l in kept[j:]]


def render(blocks):
    """blocks: ('sec', title) 或 ('line', text) → markdown。"""
    out, buf = [], []

    def flush():
        if buf:
            txt = "".join(x.strip() for x in buf)
            if txt:
                out.append(txt)
            buf.clear()

    for kind, val in blocks:
        if kind == "sec":
            flush()
            out.append("")
            out.append("### " + val.strip())
            continue
        s = val.strip()
        if not s:
            flush()
            continue
        if ENTRY_RE.match(s):
            flush()
        buf.append(s)
        if SENT_END_RE.search(s):
            flush()
    flush()
    text = "\n\n".join(x for x in out if x != "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract(book) -> list:
    doc = fitz.open(ROOT / book["pdf"])
    toc = doc.get_toc()
    rt = book["running_titles"]

    parts = [(t[1], t[2] - 1) for t in toc if t[0] == 1 and PART_RE.match(t[1])]
    chapters, cur_part = [], None
    for t in toc:
        if t[0] == 1 and PART_RE.match(t[1]):
            cur_part = t[1]
        elif t[0] == 2 and cur_part:
            m = CHAP_RE.match(t[1])
            if m:
                chapters.append((cur_part, m.group(1), m.group(2).strip() or t[1], t[2] - 1))
    if not chapters:
        print(f"❌ {book['title']}：未解析到章")
        return []

    boundaries = sorted({p for _t, p in parts} | {c[3] for c in chapters} | {doc.page_count})
    out_dir = ROOT / book["out"]
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for idx, (part, chap_no, chap_name, p0) in enumerate(chapters, 1):
        end = min(b for b in boundaries if b > p0) - 1
        secs = {}
        for t in toc:
            if t[0] == 3 and p0 <= t[2] - 1 <= end:
                secs.setdefault(t[2] - 1, []).append(t[1])
        blocks = []
        for pno in range(p0, end + 1):
            raw = [l.rstrip() for l in doc[pno].get_text().splitlines()]
            nonempty = [l for l in raw if l.strip()]
            # 章首「纯纲要页」（章标题 + 节列表，无正文）→ 跳过
            if pno == p0 and len(nonempty) <= 12 and not any(
                    ("。" in l or "！" in l or "？" in l) for l in nonempty):
                continue
            starts = secs.get(pno, [])
            lines = clean_page(raw, strip_titles=(bool(starts) or pno == p0), running_titles=rt)
            for s in starts:
                blocks.append(("sec", s))
            for l in lines:
                blocks.append(("line", l))
        text = render(blocks)
        part_no = PART_RE.match(part).group(1)
        fname = f"{idx:02d}-{part_no}{chap_no} {chap_name}.md"
        (out_dir / fname).write_text(
            f"# {part} · {chap_no} {chap_name}\n\n"
            f"> 来源：{Path(book['pdf']).name} 第 {p0 + 1}–{end + 1} 页\n\n{text}\n",
            encoding="utf-8",
        )
        report.append((fname, part, chap_no, chap_name, p0 + 1, end + 1, len(text)))
        print(f"  ✅ {fname}  (p{p0 + 1}–{end + 1}, {len(text)} 字)")
    doc.close()

    lines = [f"# {book['title']} — 知识库索引", "",
             f"- 来源：{Path(book['pdf']).name}",
             f"- 角色：{book['role']}",
             "- 提取策略：TOC 书签驱动，按「章」切分（节以 `###` 标出）",
             "- ⚠️ 文字层为 OCR 产物，含噪声（笫→第、侦→债、千→于 等），引用需复核", "",
             "| 文件 | 部/编 | 章 | 页码 |", "|---|---|---|---|"]
    for fname, part, chap_no, chap_name, a, b, _n in report:
        lines.append(f"| {fname} | {part} | {chap_no} {chap_name} | {a}-{b} |")
    lines += ["", "## 使用说明", "",
              "- 本角色书不进判分链（判分只锚主线书习题册）。",
              "- 法条落地以大陆《民法典》为准（经 `kb/laws/` 或 law-verifier 核对）。"]
    (ROOT / book["readme"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ {book['title']}：{len(report)} 章 → {book['out']}")
    return report


def main():
    for book in BOOKS:
        print("=" * 50)
        extract(book)
    return 0


if __name__ == "__main__":
    sys.exit(main())
