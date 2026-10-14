# -*- coding: utf-8 -*-
"""
王泽鉴《民法学说与判例研究》重排合订本提取器

书签是按页编号（无章节语义），但正文 PDF 页 = 印刷页 + 10（目录印在第 5-10 页）。
本脚本：解析目录页（印刷页码 + 论文标题）→ 按「编」切分正文 → 每编一个 md。

用法：
  python tools/extract_wzj.py extract
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
PDF = next(Path("material/inbox").glob("民法学说与判例研究*.pdf"))
OUT = ROOT / "kb" / "民法学说与判例研究-王泽鉴" / "教材"
OFFSET = 9  # 印刷页 → PDF 0-based 索引 的偏移（封面1/书名3/版权4/目录5-10；印刷页N=PDF第N+10页=0-based N+9）

# 目录里「一、二、三…」章号标记与已知章名（无页码，须与论文标题区分）
CHAPTER_NAMES = {"债法通论与契约", "侵权行为", "不当得利", "无因管理", "债之效力",
                 "物权通论", "用益物权、担保物权及优先权"}
BIAN_RE = re.compile(r"^第([一二三四五六七八九十]+)编$")

# 页码行（OCR 噪声：】』Ⅰ 都是 1，' 是前导符）
def parse_page(s):
    s = s.strip().lstrip("'′’").replace("】", "1").replace("』", "1").replace("Ⅰ", "1").replace("l", "1")
    s = re.sub(r"\s+", "", s)
    if re.fullmatch(r"\d{1,4}", s):
        return int(s)
    return None


def parse_toc(doc):
    """目录页(p.5-10, 0-based 4-9) → [(编, 章, 论文标题, 印刷页)]。"""
    lines = []
    for p in range(4, 10):
        for ln in doc[p].get_text().splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)
    entries = []
    cur_bian = ""
    cur_zhang = ""
    buf = []
    pending_bian_name = False
    for ln in lines:
        if ln in ("目录", "民法学说与判例研究"):
            continue
        m = BIAN_RE.match(ln)
        if m:
            cur_bian = f"第{m.group(1)}编"
            buf = []
            pending_bian_name = True
            continue
        if pending_bian_name:
            cur_bian = f"{cur_bian} {ln}"  # 编名：法学方法论/民法总则/债法/物权法/亲属法
            pending_bian_name = False
            buf = []
            continue
        if ln in ("一", "二", "三", "四", "五", "六", "七", "八"):
            continue
        pg = parse_page(ln)
        if pg is not None:
            title = "".join(buf).strip()
            if title:
                entries.append((cur_bian, cur_zhang, title, pg))
            buf = []
        else:
            # 章名行（无页码）→ 识别为章
            hit = ln in CHAPTER_NAMES
            if hit:
                cur_zhang = ln
                buf = []
            else:
                buf.append(ln)
    return entries


def extract():
    doc = fitz.open(PDF)
    entries = parse_toc(doc)
    if not entries:
        print("❌ 目录解析为空")
        return 1
    # 按编分组
    from collections import OrderedDict
    groups = OrderedDict()
    for bian, zhang, title, pg in entries:
        groups.setdefault(bian, []).append((zhang, title, pg))
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for bi, (bian, papers) in enumerate(groups.items()):
        p0 = papers[0][2] + OFFSET
        p1 = (papers[-1][2] + OFFSET) if bi + 1 == len(groups) else (groups[list(groups.keys())[bi + 1]][0][2] + OFFSET - 1)
        p1 = min(p1, doc.page_count - 1)
        # 正文：按论文标题插入 ## 标记
        body = []
        last_zhang = None
        for i, (zhang, title, pg) in enumerate(papers):
            start = pg + OFFSET
            end = (papers[i + 1][2] + OFFSET - 1) if i + 1 < len(papers) else p1
            if zhang and zhang != last_zhang:
                body.append(f"## {zhang}\n")
                last_zhang = zhang
            body.append(f"### {title}\n")
            for pno in range(start, end + 1):
                t = doc[pno].get_text().strip()
                if t:
                    body.append(t)
            body.append("")
        text = "\n\n".join(body)
        fname = f"{bi + 1:02d}-{bian}.md"
        (OUT / fname).write_text(
            f"# {bian}\n\n> 来源：{PDF.name} 印刷页 {papers[0][2]}–{papers[-1][2]}（PDF 页 {p0 + 1}–{p1 + 1}）\n\n{text}\n",
            encoding="utf-8",
        )
        report.append((fname, bian, len(papers), p0, p1))
        print(f"  ✅ {fname}  {len(papers)} 篇  (PDF {p0 + 1}–{p1 + 1})")
    doc.close()
    # README
    lines = [f"# 民法学说与判例研究（王泽鉴）— 知识库索引", "",
             f"- 来源：{PDF.name}", "- 角色：专题参考", "- 提取策略：目录页码解析 + 按编切分", ""]
    lines += ["| 文件 | 编 | 论文数 | 印刷页 |", "|---|---|---|---|"]
    for fname, bian, n, p0, p1 in report:
        lines.append(f"| {fname} | {bian} | {n} | {p0 - OFFSET}–{p1 - OFFSET} |")
    lines += ["", "## 使用说明", "",
              "- 每编一个文件，论文以 `###` 标题列出；本编内 `##` 为分章（债法/物权法有分章）。",
              "- 本书以台湾地区\"民法\"条文为主要示例：讲原理与方法按王本，法条落地一律以大陆《民法典》条文为准。",
              "- 本角色书不进判分链。"]
    (OUT.parent / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ 共 {len(groups)} 编 → kb/民法学说与判例研究-王泽鉴/")
    return 0


if __name__ == "__main__":
    sys.exit(extract())
