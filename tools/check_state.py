#!/usr/bin/env python3
"""收工前状态对账：校验复习队列/错题档案计数、最近触及日期、notes 章目录命名。"""
import re
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent

QUEUE = "kb/民法总论/复习队列.md"
WRONG = "kb/民法总论/错题档案.md"
TREE = "进程树.md"
NOTES_MZ = "notes/民法总论"
NOTES_ZF = "notes/债法总论-解亘"

_DATE = r"20\d\d-\d\d-\d\d"
DATE_ANY = re.compile(_DATE)
DATE_EXACT = re.compile(r"^" + _DATE + r"$")
TOUCH_HEADER = re.compile(r"复习队列：\s*(\d+)\s*项（民法总论）")
WRONG_HEADER = re.compile(r"错题档案：\s*(\d+)\s*道")
CN_DIGITS = "零一二三四五六七八九十百"


def read(rel):
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def rows(text, prefix):
    """表格数据行：以 prefix 开头、非分隔行、且含日期；表头无日期故自然落选。"""
    out = []
    for line in text.splitlines():
        if line.startswith(prefix) and not line.startswith("|---") and DATE_ANY.search(line):
            out.append(line)
    return out


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def check_queue_count(state):
    queue, tree = read(QUEUE), read(TREE)
    if queue is None:
        return "skip", "文件不存在：%s" % QUEUE
    if tree is None:
        return "skip", "文件不存在：%s" % TREE
    n = len(rows(queue, "| "))
    m = TOUCH_HEADER.search(tree)
    if not m:
        return "fail", "进程树未找到「复习队列：N 项（民法总论）」声明（文件 %d 行）" % n
    if int(m.group(1)) != n:
        return "fail", "复习队列计数漂移：文件 %d 行 vs 进程树声明 %s" % (n, m.group(1))
    return "pass", "复习队列 %d 行 == 进程树声明 %s 项" % (n, m.group(1))


def check_wrong_count(state):
    wrong, tree = read(WRONG), read(TREE)
    if wrong is None:
        return "skip", "文件不存在：%s" % WRONG
    if tree is None:
        return "skip", "文件不存在：%s" % TREE
    n = len(rows(wrong, "| 20"))
    m = WRONG_HEADER.search(tree)
    if not m:
        return "skip", "进程树无「错题档案：M 道」声明，跳过（文件 %d 道）" % n
    if int(m.group(1)) != n:
        return "fail", "错题档案计数漂移：文件 %d 道 vs 进程树声明 %s 道" % (n, m.group(1))
    return "pass", "错题档案 %d 道 == 进程树声明 %s 道" % (n, m.group(1))


def check_touch_dates(state):
    queue = read(QUEUE)
    if queue is None:
        return "skip", "文件不存在：%s" % QUEUE
    bad = []
    for line in rows(queue, "| "):
        cols = cells(line)
        value = cols[2] if len(cols) > 2 else ""
        ok = bool(DATE_EXACT.match(value))
        if ok:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                ok = False
        if not ok:
            bad.append((value, line))
    if bad:
        detail = "「最近触及」非合法 YYYY-MM-DD 共 %d 行：" % len(bad)
        for value, line in bad:
            detail += "\n      取到 %r ← %s" % (value, line)
        return "fail", detail
    return "pass", "「最近触及」列日期格式全部合法"


def chapter_dirs(rel):
    base = ROOT / rel
    if not base.is_dir():
        return None
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def styles(names):
    arabic = [n for n in names if re.match(r"^第\d+章", n)]
    chinese = [n for n in names if re.match(r"^第[%s]+章" % CN_DIGITS, n)]
    return arabic, chinese


def check_notes_naming(state):
    names = chapter_dirs(NOTES_MZ)
    if names is None:
        return "skip", "目录不存在：%s" % NOTES_MZ
    arabic, chinese = styles(names)
    problems = []
    if arabic and chinese:
        problems.append("章目录命名混用（阿拉伯 %d 个 %s / 中文 %d 个 %s）"
                        % (len(arabic), arabic, len(chinese), chinese))
    zf = chapter_dirs(NOTES_ZF)
    if zf is None:
        state["notes"].append("提示：目录不存在：%s" % NOTES_ZF)
    else:
        z_arabic, z_chinese = styles(zf)
        if z_arabic or z_chinese:
            state["notes"].append("提示：%s 出现「第X章」目录（本书为「第X部」层级）：%s"
                                  % (NOTES_ZF, z_arabic + z_chinese))
    if problems:
        return "fail", "\n      ".join(problems + ["全部子目录：%s" % names])
    return "pass", "%s 章目录命名未混用（%s）" % (NOTES_MZ, names)


CHECKS = [
    ("复习队列数据行数 vs 进程树声明", check_queue_count),
    ("错题档案数据行数 vs 进程树声明", check_wrong_count),
    ("复习队列「最近触及」日期格式", check_touch_dates),
    ("notes 章目录命名一致性", check_notes_naming),
]


def main():
    state = {"notes": []}
    passed = failed = skipped = 0
    for i, (title, fn) in enumerate(CHECKS, 1):
        print("[CHECK] %d/%d %s" % (i, len(CHECKS), title))
        status, detail = fn(state)
        if status == "pass":
            passed += 1
            print("[OK] %s" % detail)
        elif status == "fail":
            failed += 1
            print("[FAIL] %s" % detail)
        else:
            skipped += 1
            print("[SKIP] %s" % detail)
    for note in state["notes"]:
        print("[NOTE] %s" % note)
    summary = "通过 %d / 失败 %d" % (passed, failed)
    if skipped:
        summary += " / 跳过 %d" % skipped
    print(summary)
    if failed:
        return 1
    if skipped:
        print("SKIPPED %d" % skipped)
        return 0
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
