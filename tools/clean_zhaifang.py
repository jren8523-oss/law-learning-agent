# -*- coding: utf-8 -*-
"""张焕然债法课件 PDF 提取稿 → 清洗 + 按「部分」切分 markdown（v2）。

输入：_tmp_ocr/张焕然债法_dump.txt
输出：_tmp_ocr/张焕然债法_clean/*.md

v2 修正：
  - 部分/编 只认「规范标题」精确匹配（避免 TOC 图框标签误触发）。
  - 切换部分时先 flush 旧部分再写新文件名（修 0KB bug）。
  - 跳过「目录/总览页」（一页内出现 ≥3 个结构标题，视为图框目录）。
  - 全角冒号归一为空格后再匹配标题。
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(r"D:\law-learning-agent")
SRC = ROOT / "_tmp_ocr" / "张焕然债法_dump.txt"
OUT = ROOT / "_tmp_ocr" / "张焕然债法_clean"

PART_TITLES = {
    "第一部分 债法总论",
    "第二部分 合同法",
    "第三部分 无因管理与不当得利",
    "第四部分 侵权法",
}
BIAN_TITLES = {
    "第一编 合同法总论",
    "第二编 合同法分论",
    "第一编 侵权法总论",
    "第二编 侵权法分论",
}

PART_RE = re.compile(r"^(第[一二三四五六七八九十]+部分)\s*(.*)$")
BIAN_RE = re.compile(r"^(第[一二三四五六七八九十]+编)\s*(.*)$")
ZHANG_RE = re.compile(r"^(第[一二三四五六七八九十]+章)\s*(.*)$")
JIE_RE = re.compile(r"^(第[一二三四五六七八九十]+节)\s*(.*)$")
BARE_RE = re.compile(r"^第[一二三四五六七八九十]+(?:部分|[编章节])$")
NUM_RE = re.compile(r"^\d{1,4}$")

FOOTER = {"债法总论", "合同法", "无因管理与不当得利", "侵权法", "无因管理", "不当得利"}

BOILER = {
    "©张焕然", "© 张焕然", "中国政法大学", "中国政法大学民法研究所",
    "授课教师：张焕然", "授课教师 张焕然", "授课教师： 张焕然",
    "本章目录", "目录", "谢谢！", "谢谢",
    "开场白", "课程内容概览", "授课安排",
}


def normalize(s: str) -> str:
    return s.replace("：", " ").replace("　", " ").strip()


def classify(line: str):
    """返回 (kind, title) 或 None。kind ∈ {part, bian, zhang, jie}。"""
    s = normalize(line)
    if s in PART_TITLES:
        return "part", s
    if s in BIAN_TITLES:
        return "bian", s
    m = ZHANG_RE.match(s)
    if m and m.group(2).strip():
        return "zhang", f"{m.group(1)} {m.group(2).strip()}"
    m = JIE_RE.match(s)
    if m and m.group(2).strip():
        return "jie", f"{m.group(1)} {m.group(2).strip()}"
    return None


def is_struct(line: str) -> bool:
    return classify(line) is not None


def main():
    raw = SRC.read_text(encoding="utf-8").lstrip("\ufeff")
    pages = re.split(r"===== PAGE \d+ =====", raw)
    OUT.mkdir(exist_ok=True)

    cur_part = None      # 规范部分标题
    cur_bian = None      # 规范编标题
    cur_zhang = None
    cur_jie = None
    cur_file = None
    buf = []
    last_line = None

    def flush():
        nonlocal buf
        if cur_file is not None and buf:
            path = OUT / f"{cur_file}.md"
            path.write_text("\n".join(buf).rstrip() + "\n", encoding="utf-8")
        buf = []

    def open_part(title):
        nonlocal cur_part, cur_bian, cur_zhang, cur_jie, cur_file, buf, last_line
        flush()
        cur_part = title
        cur_bian = cur_zhang = cur_jie = None
        cur_file = title
        buf = [f"# {title}"]
        last_line = None

    for page in pages[1:]:
        lines = [normalize(l) for l in page.splitlines()]
        lines = [l for l in lines if l]

        # 目录/总览页：裸结构标记 + 带题章标题 ≥3 → 整页跳过（图框目录）
        bare_count = sum(1 for l in lines if BARE_RE.match(l))
        zhang_count = sum(
            1 for l in lines
            if (m := ZHANG_RE.match(l)) and m.group(2).strip()
        )
        jie_titles = [
            l for l in lines
            if (m := JIE_RE.match(l)) and m.group(2).strip()
        ]
        if bare_count + zhang_count >= 3:
            continue
        # 「本章目录」页：只留章标题，节标题列表交给正文页的 running header 去建
        is_toc = (zhang_count == 1 and len(jie_titles) >= 2)

        for ln in lines:
            if not ln:
                continue
            if ln in BOILER or ln in FOOTER:
                continue
            if BARE_RE.match(ln) and len(ln) <= 6:
                continue
            if NUM_RE.match(ln):
                continue
            if len(ln) == 1 and not ln.isascii():
                continue  # 单汉字图框散字
            if is_toc:
                m = JIE_RE.match(ln)
                if m and m.group(2).strip():
                    continue  # 目录页的节列表不输出

            kind = classify(ln)
            if kind:
                k, title = kind
                if k == "part":
                    if title != cur_part:
                        open_part(title)
                elif k == "bian":
                    if title != cur_bian:
                        cur_bian = title
                        cur_zhang = cur_jie = None
                        buf.append(f"\n## {title}")
                        last_line = None
                elif k == "zhang":
                    if title != cur_zhang:
                        cur_zhang = title
                        cur_jie = None
                        lvl = "###" if cur_bian else "##"
                        buf.append(f"\n{lvl} {title}")
                        last_line = None
                elif k == "jie":
                    if title != cur_jie:
                        cur_jie = title
                        lvl = "####" if cur_bian else "###"
                        buf.append(f"\n{lvl} {title}")
                        last_line = None
                continue

            # 普通正文：相邻去重
            if ln == last_line:
                continue
            buf.append(ln)
            last_line = ln

    flush()
    print("done. files:")
    for p in sorted(OUT.glob("*.md")):
        print(f"  {p.name}  ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
