# -*- coding: utf-8 -*-
"""
王泽鉴「重排版」PDF（带文字层）→ 按章 markdown 提取器

用法：
  python tools/extract_wzj_book.py detect          # 只打印章/节结构，不写文件
  python tools/extract_wzj_book.py extract         # 提取 BOOKS 全部
  python tools/extract_wzj_book.py extract --only 民法物权

设计（针对北大社 2022–2023 重排版 OCR 文字层）：
  1. 页眉（y < 75）剔除；从页眉数字还原「原书页码」，正文行前插 <!-- p.N --> 定位标记。
  2. 同一 y 的多个 span（跨块被切开的行）按 x 合并成 row → 再按「大间距 / 首行缩进」断段；
     跨页未结束的段落自动接续。
  3. 章标题、节标题取自 PDF 书签（OCR 正文里的标题常有错字），节标题用模糊匹配注入正文。
  4. 脚注块（底部大间距 + 小字号）整块抽出，统一放章末「注释」。
  5. 最小 OCR 清噪（笫→第、巳→已、＠→②、常见「千→于」词表、CD→①），不做激进改写。

输出：
  kb/<书名>/教材/NN-第X章 章名.md
  kb/<书名>/README.md
"""
import argparse
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "material" / "inbox"

BOOKS = [
    {
        "key": "民法物权",
        "title": "民法物权（第二版）",
        "author": "王泽鉴",
        "glob": "*民法物权*王泽鉴*.pdf",
        "out": ROOT / "kb" / "民法物权-王泽鉴",
        "role": "对照",
        "edition": "第二版（2023 年重印版）",
    },
    {
        "key": "不当得利",
        "title": "不当得利（第二版）",
        "author": "王泽鉴",
        "glob": "*不当得利*王泽鉴*.pdf",
        "out": ROOT / "kb" / "不当得利-王泽鉴",
        "role": "对照",
        "edition": "第二版（2023 年重排版）",
    },
]

CH_RE = re.compile(r"^第[一二三四五六七八九十百—–\-]+章")
SEC_RE = re.compile(r"^第[一二三四五六七八九十百]+节")
STOP_RE = re.compile(r"^(主要参考书目|索引|附录|人名索引|事项索引)")
FRONT_RE = re.compile(r"^(总序|.*重排版说明|.*序言|物权法的现代化)")

HEAD_CUT = 75      # 页眉区：y < HEAD_CUT 剔除
FOOT_MARGIN = 50   # 页脚区：y > page.height - FOOT_MARGIN 剔除
ROW_TOL = 7        # 同一行的 y 容差
PARA_GAP = 20      # 行间距 > 该值 → 断段
INDENT_TOL = 12    # x0 比版心左界多出该值 → 断段（首行缩进）
FOOT_GAP = 25      # 脚注块：与上文间距 > 该值
FOOT_SIZE = 8.8    # 脚注块：字号中位数 < 该值
FOOT_YMIN_RATIO = 0.55  # 脚注块：起始 y 需 > 页高 * 该值
SEC_SIM = 0.85     # 节标题模糊匹配阈值
TITLE_SIZE = 15.5  # 章名大字块（OCR 常乱码）：直接丢，章名由书签补齐（节标题最大约 14.9）

# ── 最小 OCR 清噪 ────────────────────────────────────────────────
FIX_CHAR = {"笫": "第", "笚": "第", "巳": "已", "＠": "②"}
FIX_PHRASE = {"自已": "自己", "有助千": "有助于", "有害千": "有害于"}
YU_PREV = "基关属至由对是终限居善归在用趋近急忙等鉴富乐难易陷迫偏宜慎勤忠专精通见信疑敢惯苦甘大高多少久低强重先后"
NUMERAL = "一二三四五六七八九十百千万亿数几"
QIAN_KEEP_PREV = NUMERAL + "若"   # 「若干」「数千」「一千」等真字，不替换
QIAN_BLOCK = ("王千维",)          # 人名，不替换
CJK = r"\u4e00-\u9fff"
CJK_PUNCT = r"\u3000-\u303f\uff00-\uff65\u2014\u2018-\u201d\u2026"


def clean_text(t: str) -> str:
    t = re.sub(
        r"[%s%s]\s+[%s%s]" % (CJK, CJK_PUNCT, CJK, CJK_PUNCT),
        lambda m: m.group(0)[0] + m.group(0)[-1],
        t,
    )
    t = re.sub(r"[ \t]{2,}", " ", t)
    for a, b in FIX_CHAR.items():
        t = t.replace(a, b)
    for a, b in FIX_PHRASE.items():
        t = t.replace(a, b)
    # 「千→于」：实证扫描 3222 处「千」中绝大为「于」误识；仅排除数字语境与「若千」「王千维」
    out = []
    for i, ch in enumerate(t):
        pre = t[i - 1] if i > 0 else ""
        if ch == "千" and pre not in QIAN_KEEP_PREV and t[i:i + 3] not in QIAN_BLOCK:
            out.append("于")
        elif ch == "于" and pre in "一二三四五六七八九十" and i + 1 < len(t) and t[i + 1] in "零百千万":
            out.append("千")   # 「一于零五十万」→「一千零五十万」
        else:
            out.append(ch)
    t = "".join(out)
    t = re.sub(r"(?<![A-Za-z])CD(?![A-Za-z])", "①", t)
    return t.strip()


def clean_title(t: str) -> str:
    """标题清洗：同 clean_text，但保留「第X章/节」后的分隔空格。"""
    t = clean_text(t)
    return re.sub(r"^(第[一二三四五六七八九十百]+[章节款])(?=\S)", r"\1 ", t)


def norm(s: str) -> str:
    s = s.replace("—", "一").replace("–", "一")
    s = re.sub(r"[\s%s《》“”‘’()（）]" % CJK_PUNCT, "", s)
    s = re.sub(r"[，、。：；？！,.:;?!]", "", s)
    s = s.replace("笫", "第").replace("弟", "第")
    return s


def join_parts(parts) -> str:
    """同一 y 上的水平碎片拼接：夹在拉丁字母/数字之间补一个空格。"""
    out = ""
    for p in parts:
        t = p["text"]
        if not t:
            continue
        if out and re.search(r"[A-Za-z0-9]$", out) and re.match(r"^[A-Za-z0-9]", t):
            out += " "
        out += t
    return out


def page_rows(page):
    """→ (rows, printed_page)。rows 为按 y 排序、同 y 合并后的行。"""
    lines = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            txt = "".join(s["text"] for s in ln["spans"])
            if not txt.strip():
                continue
            lines.append({
                "y": ln["bbox"][1], "x": ln["bbox"][0], "x1": ln["bbox"][2],
                "size": max(s["size"] for s in ln["spans"]), "text": txt,
            })
    lines.sort(key=lambda d: (d["y"], d["x"]))

    head_nums = []
    rows = []
    for d in lines:
        if rows and abs(d["y"] - rows[-1]["y"]) <= ROW_TOL:
            rows[-1]["parts"].append(d)
            rows[-1]["y"] = min(rows[-1]["y"], d["y"])
        else:
            rows.append({"y": d["y"], "parts": [d]})

    kept = []
    for r in rows:
        r["parts"].sort(key=lambda d: d["x"])
        r["text"] = join_parts(r["parts"])
        r["x"] = r["parts"][0]["x"]
        r["x1"] = max(p["x1"] for p in r["parts"])
        r["size"] = max(p["size"] for p in r["parts"])
        if r["y"] < HEAD_CUT:
            for tok in re.findall(r"\d{1,4}", r["text"]):
                head_nums.append(int(tok))
            continue
        if r["y"] > page.rect.height - FOOT_MARGIN:
            continue
        if r["size"] >= TITLE_SIZE:   # 章名大字块（OCR 常乱码），章名由书签补齐
            continue
        kept.append(r)

    printed = None
    for tok in head_nums:
        if 1 <= tok <= 9999:
            printed = tok
            break
    return kept, printed


def build_paragraphs(rows):
    """rows → (正文段落列表, 脚注段落列表)。脚注块由「大间距 + 小字号」判定。"""
    body, foots = rows, []
    # 从底往上找：最后一个「大间距」且其后字体整体偏小（中位数）的位置 = 脚注块起点。
    # 取「最后一个」而非「第一个」，避免把脚注上方的正文（如节标题、案例）误吞进去。
    max_y = max(r["y"] for r in rows) if rows else 0
    for i in range(len(rows) - 1, 0, -1):
        gap = rows[i]["y"] - rows[i - 1]["y"]
        rest = rows[i:]
        if gap < FOOT_GAP or len(rest) < 2:
            continue
        sizes = sorted(r["size"] for r in rest)
        med = sizes[len(sizes) // 2]
        if med < FOOT_SIZE and rows[i]["y"] > FOOT_YMIN_RATIO * max_y:
            body, foots = rows[:i], rest
            break

    def pack(rs):
        out, cur = [], None
        for r in rs:
            txt = clean_text(r["text"])
            if not txt:
                continue
            is_head = bool(SEC_RE.match(txt) or CH_RE.match(txt))
            new = cur is None or is_head or (r["y"] - cur["_last_y"]) > PARA_GAP \
                or (r["x"] - cur["_left"]) > INDENT_TOL
            if new:
                cur = {"text": txt, "_left": r.get("_left", r["x"]), "_last_y": r["y"]}
                out.append(cur)
            else:
                if re.search(r"[A-Za-z0-9]$", cur["text"]) and re.match(r"^[A-Za-z0-9]", txt):
                    cur["text"] += " "
                cur["text"] += txt
                cur["_last_y"] = r["y"]
        return out

    if body:
        lefts = sorted(r["x"] for r in body)
        body_left = lefts[max(0, len(lefts) // 10)]
        for r in body:
            r["_left"] = body_left
    return pack(body) if body else [], pack(foots)


def norm_title(s: str) -> str:
    return norm(s)


def match_section(rowtext: str, sec_title: str) -> bool:
    a, b = norm_title(rowtext), norm_title(sec_title)
    if not b:
        return False
    if len(a) > len(b) + 8:
        return False
    # 标题常被跨行/跨页拆开：正文行只是标题的前缀时按前缀比对
    if len(a) <= len(b):
        a, b = a, b[:max(len(a), 1)]
    return difflib.SequenceMatcher(None, a, b).ratio() >= SEC_SIM


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", s).strip()


def detect_chapters(doc):
    """书签 → (chapters, sections, front)。chapters/sections 的元素为 (title, start_pdf)。"""
    toc = doc.get_toc()
    chapters, sections, front = [], [], []
    toc_page = None
    stop_page = None
    for lvl, title, page in toc:
        t = title.replace("第—章", "第一章").replace("第–章", "第一章").replace("第-章", "第一章")
        t = clean_title(t)
        if lvl == 1 and CH_RE.match(t) and not STOP_RE.match(t):
            chapters.append((t, page))
        elif lvl == 1 and STOP_RE.match(t):
            stop_page = page if stop_page is None else min(stop_page, page)
        elif lvl == 2 and SEC_RE.match(t) and chapters:
            sections.append((clean_title(t), page))
        if t.strip() in ("目录", "目 录") and toc_page is None:
            toc_page = page
    for lvl, title, page in toc:
        if lvl == 1 and (FRONT_RE.match(title) or "重排版说明" in title):
            front.append((title, page))
    chapters.sort(key=lambda x: x[1])
    sections.sort(key=lambda x: x[1])
    return chapters, sections, front, toc_page, stop_page


def extract_book(book, write=True):
    matches = [p for d in (ROOT / "material" / "pdf", INBOX) if d.is_dir()
               for p in sorted(d.glob(book["glob"]))]
    if not matches:
        print("!! 找不到 PDF：", book["glob"])
        return False
    pdf = matches[0]
    doc = fitz.open(pdf)
    chapters, sections, front, toc_page, stop_page = detect_chapters(doc)

    # 原书页码偏移：由各页页眉数字投票得出
    offs = Counter()
    for i in range(doc.page_count):
        _, printed = page_rows(doc[i])
        if printed:
            offs[i + 1 - printed] += 1
    offset = offs.most_common(1)[0][0] if offs else 0

    outdir = book["out"] / "教材"
    if write:
        outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 74)
    print(f"{book['title']}（{book['author']}）  {pdf.name}")
    print(f"  页数 {doc.page_count} | 章 {len(chapters)} | 节 {len(sections)} | 原书页偏移 {offset}")

    bounds = [c[1] for c in chapters] + [stop_page or (doc.page_count + 1)]
    index_rows, sec_miss = [], []

    def render(pages, title, sec_list, mode="printed", first_of_chapter=False):
        """pages: 0-based 列表；返回 markdown 正文行 + 页码区间。"""
        sec_list = list(sec_list)
        lines, notes, first_p, last_p = [], [], None, None
        open_para = None
        for pno in pages:
            rows, printed = page_rows(doc[pno])
            if mode == "printed":
                pp = printed if (printed and printed >= 1) else pno + 1 - offset
                label = f"p.{pp}"
            else:
                pp, label = pno + 1, f"PDF p.{pno + 1}"
            if first_p is None:
                first_p = pp
            last_p = pp
            body, foots = build_paragraphs(rows)
            if first_of_chapter and pno == pages[0]:
                # 章首页：首个「第X节」之前的是（OCR 乱码的）章名大字块，丢弃（章名由书签补齐）
                k = next((i for i, p in enumerate(body) if SEC_RE.match(p["text"])), None)
                if k is not None:
                    body = body[k:]
                    foots = []
            lines.append(f"<!-- {label} -->")
            for para in body:
                row_text = para["text"]
                cands = [s for s in sec_list if pno + 1 >= s[1] - 1]
                hit = next((s for s in cands if match_section(row_text, s[0])), None)
                if hit is None and SEC_RE.match(row_text.strip()) and cands:
                    hit = cands[0]
                if hit:
                    sec_list.remove(hit)
                    if open_para is not None:
                        lines.append(open_para["text"])
                        open_para = None
                    lines.append("## " + clean_title(hit[0]))
                elif open_para is None:
                    open_para = para
                elif re.search(r"[。！？：；”\"]$", open_para["text"]) or open_para["text"].startswith("##"):
                    lines.append(open_para["text"])
                    open_para = para
                else:  # 跨页续段
                    open_para["text"] += row_text
            for para in foots:
                notes.append(f"- 〔{label}〕{para['text']}")
        if open_para is not None:
            lines.append(open_para["text"])
        miss = [s[0] for s in sec_list]
        return lines, notes, first_p, last_p, miss

    def write_file(fname, title, lines, notes, first_p, last_p, source, tag="原书"):
        text = [f"# {title}", "", f"> 来源：{source}", ""]
        if notes:
            text += lines + ["", "## 注释", ""] + notes
        else:
            text += lines
        p = outdir / fname
        if write:
            p.write_text("\n".join(text).rstrip() + "\n", encoding="utf-8")
        print(f"  → {fname}  {tag} pp.{first_p}-{last_p}  {'(只读)' if not write else ''}")
        return first_p, last_p

    # 前置（总序/序言）
    if write and front:
        fp = [p for t, p in front if not STOP_RE.match(t)]
        if fp:
            stop = (toc_page - 1) if toc_page else (chapters[0][1] - 1)
            pages = list(range(min(fp) - 1, stop))
            sec_list = []
            lines, notes, a, b, _ = render(pages, "序言", [], mode="pdf")
            write_file("00-序言与重排版说明.md", "序言与重排版说明", lines, notes, a, b,
                       f"{book['title']}（{book['author']}）{book['edition']} · PDF pp.{a}-{b}", tag="PDF")

    for i, (ctitle, cstart) in enumerate(chapters):
        end = bounds[i + 1]
        pages = list(range(cstart - 1, min(end, doc.page_count + 1) - 1))
        sec_list = [s for s in sections
                    if cstart <= s[1] < end and pages and s[1] <= pages[-1] + 1]
        lines, notes, a, b, miss = render(pages, ctitle, sec_list, first_of_chapter=True)
        sec_miss += miss
        fname = f"{i + 1:02d}-{safe_name(ctitle)}.md"
        write_file(fname, ctitle, lines, notes, a, b,
                   f"{book['title']}（{book['author']}）{book['edition']} · 原书 pp.{a}-{b}")
        index_rows.append((fname, ctitle, a, b))

    # README
    readme = [
        f"# {book['title']}（{book['author']}）— 知识库索引",
        "",
        f"> 来源：`material/pdf/{pdf.name}`（{doc.page_count} 页）",
        f"> 角色：**{book['role']}**（华政学硕参考书目）——观点分歧时的对比材料，**不进判分链**。",
        f"> 页码：正文 `<!-- p.N -->` 为**原书页码**；PDF 页 = 原书页 + {offset}。",
        "> 法条以王本台湾地区「民法」条文为示例讲解；**大陆法条落地一律以《民法典》为准**。",
        "",
        "| 文件 | 章 | 原书页 |",
        "|---|---|---|",
    ]
    for fname, ctitle, a, b in index_rows:
        readme.append(f"| {fname} | {ctitle} | {a}-{b} |")
    readme += [
        "",
        "## 提取说明",
        "",
        f"- 由 `tools/extract_wzj_book.py` 从 PDF 文字层提取：章/节标题取自书签，正文按版面几何重建段落。",
        f"- 已剔除页眉页脚；章首页的章名大字块（OCR 常乱码）丢弃，章名一律以书签为准。",
        "- 脚注（底部大间距 + 小字号块）抽出，按原书页码收在每章末尾「注释」。",
        "- 已做最小 OCR 清噪，**未做激进改写**：`笫/笚→第`、`巳→已`、`＠→②`、`CD→①`；",
        "  `千→于`（实测全书 3222 处「千」中绝大多数为「于」误识，仅保留数字语境「一千/数千」与「若干」「王千维」）。",
        "- 残留 OCR 噪声提示：脚注标记 ② 有时误作「心」，个别字（如「之」误作「卫」）仍存，表格/流程图文字多为乱码；",
        "  引用原文前请回溯 PDF 对应页核对（每页已插 `<!-- p.N -->` 定位）。",
        "",
        "> 序言/参考书目/索引：序言已提取为 `00-序言与重排版说明.md`；参考书目与索引未提取，需要时查原 PDF。",
        "> 同类脚本：`tools/extract_zhaifa.py`（债法书，同属 TOC 书签驱动）；本脚本额外做节标题注入、脚注抽出与原书页码还原。",
    ]
    if write:
        (book["out"] / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"  未注入的节标题：{len(sec_miss)} 处")
    for m in sec_miss:
        print(f"     ! {m}")
    doc.close()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["detect", "extract"])
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    for book in BOOKS:
        if args.only and args.only not in book["key"]:
            continue
        extract_book(book, write=(args.cmd == "extract"))


if __name__ == "__main__":
    main()
