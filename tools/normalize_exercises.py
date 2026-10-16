# -*- coding: utf-8 -*-
"""习题册 md 规范化与校验（法学学习项目）

背景：`kb/民法总论/习题/` 的 md 原先由 PDF 按 TOC 分页抽取、未做版面过滤，于是把
页脚页码（`·157 ·`）、页眉书眉（`民法总论习题集`/`单元练习一：民法概念论`）、
水印杂字（`账 帐 沙 汉 飞 淞 胀 揪 …`、`X117 W117 VK111 Xinjiang`）、
扫描分隔线残渣（`-----…----`）都带了进来，并且水印杂字会插进词里
（`越账权`←越权、`法律行淞为`←法律行为、`WK11同的`←合同的）——
这种污染会直接毁掉判分。选择题答案还被压成一串（`CBBDB;DCDBC`），只能靠数序号对齐。

本工具把习题文件**从 PDF 重建**，三道过滤（去页眉页脚、去水印杂字行、正文列裁剪），
然后把选择题答案输出成「题号 → 答案」逐条清单，最后做两个校验：

  ① 逐单元比对：题目题号数 vs 答案条数（单选/多选分开）
  ② 与旧 md 做汉字集合差：旧有新无的字必须全是水印杂字，出现正字即报警

用法：
    python tools/normalize_exercises.py check-md # 纯 md 对账（无第三方依赖）
    python tools/normalize_exercises.py report   # 只读，打印报告（从 PDF 重建后比对）
    python tools/normalize_exercises.py apply    # 写入（先整目录备份到 .bak-<时间戳>/）

注意：**只重排版面**，不改题干、选项、答案文字（含错别字一律照旧）。
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# fitz（PyMuPDF）惰性导入：仅 report/apply 模式需要；check-md 模式不依赖第三方库。
ROOT = Path(__file__).resolve().parent.parent
QA_DIR = ROOT / "kb" / "民法总论" / "习题"
PDF = ROOT / "material" / "pdf" / "民法总论习题集 杨代雄 2024超清文字版.pdf"

# ────────────────────────────── 正则 ──────────────────────────────

# 页码行：·157 ·、-·5 ·、·164、0·、12
PAGE_NO_RE = re.compile(r"^[\s·•\-–—]*\d{1,4}[\s·•\-–—]*$")
# 书眉/页脚字样
HEAD_TEXT_RE = re.compile(r"^(单元练习[一二三四五六七八九十]+：|民法总论习题集|习题集|期末模拟卷)")
# 大题标题（白名单，防止把正文里的「一、」当标题）
SECTION_HEAD_RE = re.compile(
    r"([一二三四五六七八九十]+、\s*(?:单项选择|多项选择|单选|多选|判断|辨析|简答|论述|案例分析|法条解释|名词解释)题)"
)
_HEAD_TAIL = r"(?:\s*[(（][^)）]{0,25}[)）])?"
# 用于拆行：额外吞掉标题后的「(每小题1分，共10分)」
SECTION_SPLIT_RE = re.compile(r"(?<![# ])([一二三四五六七八九十]+、\s*(?:单项选择|多项选择|单选|多选|判断|辨析|简答|论述|案例分析|法条解释|名词解释)题" + _HEAD_TAIL + r")")
RUNNING_HEAD_TEXTS = {"民法总论", "民法总论习题集", "习题集", "民法总论习题选"}
CHOICE_HEAD_RE = re.compile(r"[一二三四五六七八九十]+、\s*(?:单项选择|多项选择|单选|多选|判断)题")
PROSE_HEAD_RE = re.compile(r"[一二三四五六七八九十]+、\s*(?:辨析|简答|论述|案例分析|法条解释|名词解释)题")
OPTION_RE = re.compile(r"(?<=[\u4e00-\u9fff）)】》」』”\"?.。！？；：、A-D])([ABCD])\s*[.．](?=\s*\S)")
# 粘连的题号：仅在「句末标点 + 数字 + . 或 、」时拆（避免误伤「3.5」「为4.什么」）
QNUM_RE = re.compile(r"(?<=[。？！：:）)】”])\s?(\d{1,2})[.、](?=[\u4e00-\u9fffA-Z《“])")
# 段首标记：新题/新选项/新大题 → 另起一段
MARKER_RE = re.compile(r"^(?:## |[ABCD][.、]|\d{1,2}[.、]|[一二三四五六七八九十]+、)")
SENT_END_RE = re.compile(r"[。！？”」』）)]$")

X_LO, X_HI = 40.0, 390.0  # 正文列（水印杂字多在 x<40 或 x>390）
Y_MIN, Y_MAX = 60.0, 645.0  # 正文纵向范围（页脚页码在 y≈620+）
# 水印字体：FangSong ≥11pt 的短行（`淞 沙 账 帐 渺 …`）
WM_FONTS = ("FangSong", "KaiTi", "STKaiti", "SimHei")


# ────────────────────────────── 通用文本工具 ──────────────────────────────


def split_head(text: str) -> tuple[str, str]:
    """把 md 拆成 (文件头: # 标题 + > 来源 + 空行, 正文)。

    只在文件开头的连续头部区内切，不会把正文里的 `## 一、单项选择题` 误当头部。
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].startswith(">") or not lines[i].strip()):
        i += 1
    head_end = 0
    for j in range(i):
        if lines[j].startswith(">"):
            head_end = j + 1
    while head_end < len(lines) and not lines[head_end].strip():
        head_end += 1
    return "\n".join(lines[:head_end]) + "\n", "\n".join(lines[head_end:])


def unit_title_from_name(name: str) -> str:
    stem = re.sub(r"^(\d+)-", "", name)
    stem = re.sub(r"-(题目|答案)\.md$", "", stem)
    return re.sub(r"\s+", "", stem)


def parse_source_pages(head: str) -> tuple[int, int] | None:
    m = re.search(r"第\s*(\d+)\s*[–\-~]\s*(\d+)\s*页", head)
    return (int(m.group(1)), int(m.group(2))) if m else None


def join_prose(lines: list[str]) -> str:
    """把 PDF 行接回段落。

    - `## 大题`、`A.`/`B.` 选项、`1.` 题号、`一、` 大题 → 各自另起一段，段内换行接回
    - 无标记的整段文字 → 按句末标点收段
    """
    out, buf = [], []
    in_marked = False

    def flush():
        nonlocal in_marked
        if buf:
            out.append("".join(buf))
            buf.clear()
        in_marked = False

    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if MARKER_RE.match(s):
            flush()
            in_marked = True
            buf.append(s)
        else:
            buf.append(s)
        if not in_marked and SENT_END_RE.search(s):
            flush()
    flush()
    return "\n".join(out)


def clean_layout(text: str) -> str:
    """段落文本的版面收尾：拆粘连的选项/大题标题/题号，压掉多余空行。"""
    text = SECTION_SPLIT_RE.sub(lambda m: "\n\n## " + m.group(1) + "\n", text)
    text = OPTION_RE.sub(lambda m: "\n" + m.group(1) + ".", text)
    text = QNUM_RE.sub(lambda m: "\n" + m.group(1) + ".", text)
    text = re.sub(r"(?m)^(## .*)$", r"\n\1\n", text)  # 大题标题前后留空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def scrub_old(text: str, title: str) -> str:
    """把旧 md 正文里的书眉/页码/水印杂字先去掉，作为汉字对比的基准。

    否则书眉上的字（`七`、`碍`、`障`、`维`）会被当成「重建丢掉的正字」而误报。
    """
    core = re.sub(r"\s+", "", title.split("：")[-1])
    keep = []
    for line in text.splitlines():
        s = re.sub(r"[·•]\s*\d{1,3}\s*[·•]?", "", line).strip()
        s = re.sub(r"(?:[-–—_…]){3,}", "", s).strip()
        s = re.sub(r"单元练习[一二三四五六七八九十]+[：:]\s*", "", s)
        s = re.sub(r"期末模拟卷\s*[(（]\s*[一二]\s*[)）]", "", s)
        for head in ("民法总论习题集", "民法总论习题选", "习题集"):
            s = s.replace(head, "")
        if s.strip() in RUNNING_HEAD_TEXTS:
            continue  # 书眉/页脚（含单独一行的「民法总论」）
        if core:
            s_norm = re.sub(r"\s+", "", s)
            if len(s_norm) >= 4 and s_norm in core:
                continue  # 书眉碎片
            s = s.replace(core, "")
        s = s.strip()
        if not s or PAGE_NO_RE.match(s) or re.fullmatch(r"[A-Za-z0-9]{2,12}", s):
            continue
        if is_noise(X_LO, s, set()):
            continue
        keep.append(s)
    return "\n".join(keep)


def cjk_set(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]", text))


PUNCT_RE = re.compile(r"[、。，；：？！（）《》“”\"'.,;:!?()\[\]…—]")


def junk_chars(doc) -> set[str]:
    """扫描全书：正文列外（x<40 或 x>390）且非页码行里的汉字 = 水印杂字。"""
    junk: set[str] = set()
    for pno in range(doc.page_count):
        for _y, x0, txt, _p in page_lines(doc[pno], ymin=0, ymax=9999):
            if X_LO <= x0 <= X_HI or PAGE_NO_RE.match(txt):
                continue
            junk |= set(re.findall(r"[\u4e00-\u9fff]", txt))
    return junk


# ────────────────────────────── PDF 版面过滤 ──────────────────────────────


def page_lines(page, ymin=Y_MIN, ymax=Y_MAX):
    """页内文本行 → [(y, x, text, props)]，按阅读顺序（纵向聚簇 + 横向）。

    props = {(字体, 字号, 方向)}，供 is_noise 判定水印。
    """
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            x0, y0 = l["bbox"][0], l["bbox"][1]
            if not (ymin <= y0 <= ymax):
                continue
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if txt:
                props = {(s["font"], round(s["size"], 1), (round(l["dir"][0], 2), round(l["dir"][1], 2)))
                         for s in l["spans"]}
                out.append((y0, x0, txt, props))
    out.sort(key=lambda t: (round(t[0] / 5), t[1]))
    return out


def is_noise(x0: float, txt: str, props: set) -> bool:
    """版面噪声判定：水印杂字 / 页码 / 页眉页脚 / 分隔线残渣。

    只按「字体 + 位置 + 字形」判定，不用「短行」这种启发式——PDF 里正文会断在
    词中间（如 `…的规定是辅` / `助规范`），短行很可能是真正的正文续行。
    """
    if PAGE_NO_RE.match(txt) or HEAD_TEXT_RE.match(txt):
        return True
    if re.fullmatch(r"[-–—…·•.>\s]+", txt):
        return True
    if x0 < X_LO or x0 > X_HI:
        return True  # 正文列之外
    if any(abs(d[1]) > 0.01 for _f, _s, d in props):
        return True  # 竖排水印
    if re.fullmatch(r"[A-Za-z0-9]{2,12}", txt):
        return True  # 水印序列号：WK11、X117、Xinjiang、Liuy…
    if any(f in WM_FONTS and sz >= 11 for f, sz, _d in props) and len(txt) <= 8 and not PUNCT_RE.search(txt):
        return True  # 仿宋大字水印：淞 沙 账 帐 渺 胀…
    return False


def pdf_lines(doc, p0: int, p1: int, title: str, track_sections=False):
    """抽取 PDF 页范围内正文行，去掉页眉/页脚/水印杂字/正文列外。

    track_sections=True（答案文件）：按大题切分，选择题答案行只保留 A–D/;。
    返回 (sections, lines)：sections=[(heading, [答案...])]，lines=文字题/题目正文行。
    """
    core = re.sub(r"\s+", "", title.split("：")[-1])
    sections: list[dict] = []
    lines: list[str] = []
    cur = None
    for pno in range(p0 - 1, p1):
        for _y, x0, txt, props in page_lines(doc[pno]):
            if HEAD_TEXT_RE.match(txt) or txt.strip() in RUNNING_HEAD_TEXTS:
                continue
            if core and len(txt) <= len(core) + 4 and core in re.sub(r"\s+", "", txt):
                continue  # 书眉：本单元标题
            if core and len(re.sub(r"\s+", "", txt)) >= 4 and re.sub(r"\s+", "", txt) in core:
                continue  # 书眉拆行后的碎片（如「意思表示的一般原理」）
            if PAGE_NO_RE.match(txt):
                continue
            if track_sections:
                bare_head = txt.split("(")[0].split("（")[0].strip()
                if CHOICE_HEAD_RE.fullmatch(bare_head) or CHOICE_HEAD_RE.fullmatch(txt):
                    cur = {"heading": bare_head if CHOICE_HEAD_RE.fullmatch(bare_head) else txt,
                           "kind": "multi" if "多" in txt else "single",
                           "lines": []}
                    sections.append(cur)
                    continue
                if PROSE_HEAD_RE.search(txt) and len(txt) <= 30 and "：" not in txt:
                    cur = None
                    lines.append("\n\n## " + txt.strip())
                    continue
                if cur is not None:
                    # 选择题答案行：只认 A–D/;（水印字符天然不符），不受「短行=杂字」规则影响
                    if re.fullmatch(r"[A-D;]+", txt.replace(" ", "")):
                        cur["lines"].append(txt.replace(" ", ""))
                    continue
            if is_noise(x0, txt, props):
                continue
            lines.append(txt)

    out = []
    for sec in sections:
        blob = "".join(sec["lines"])
        answers = [g for g in blob.split(";") if g] if sec["kind"] == "multi" else list(blob.replace(";", ""))
        out.append((sec["heading"], answers))
    return out, lines


def parse_question_options(body: str) -> list[tuple[str, int, list[str]]]:
    """题目正文 → [(大题, 题号, [选项字母...])]。用于校验选项完整性。"""
    out = []
    idx = [(m.start(), m.group(1)) for m in SECTION_HEAD_RE.finditer(body)]
    for i, (pos, name) in enumerate(idx):
        end = idx[i + 1][0] if i + 1 < len(idx) else len(body)
        seg = body[pos:end]
        marks = [(m.start(), int(m.group(1))) for m in re.finditer(r"(?m)^(\d{1,2})\.\s*\S", seg)]
        for j, (qpos, num) in enumerate(marks):
            qend = marks[j + 1][0] if j + 1 < len(marks) else len(seg)
            opts = re.findall(r"(?m)^([ABCD])\.", seg[qpos:qend])
            out.append((head_key(name), num, opts))
    return out


def check_option_integrity(body: str, answers: dict[str, list[str]]) -> list[str]:
    """校验：每题选项字母应从 A 连续、无重复，且答案字母必须落在选项内。"""
    problems = []
    for head, num, opts in parse_question_options(body):
        if "选择" not in head:
            continue  # 辨析/简答/论述/案例题无选项
        if not opts:
            problems.append(f"{head} 第{num}题：未解析到选项")
            continue
        want = list("ABCD"[: len(set(opts))])
        if sorted(set(opts)) != want or len(opts) != len(set(opts)):
            problems.append(f"{head} 第{num}题：选项为 {opts}（应为 {'/'.join(want)}，无重复）")
            continue
        ans = answers.get(head)
        if ans and num <= len(ans) and not set(ans[num - 1]) <= set(opts):
            problems.append(f"{head} 第{num}题：答案 {ans[num - 1]} 不在选项 {'/'.join(opts)} 内")
    return problems


# ────────────────────────────── 统计与重建 ──────────────────────────────


def head_key(name: str) -> str:
    """大题标题归一化：去掉「(每小题1分，共10分)」等后缀，便于题目/答案两侧对齐。"""
    return re.split(r"[(（]", name.strip())[0].strip()


def count_questions(body: str) -> dict[str, int]:
    """统计各大题下的题号数。"""
    counts = {}
    idx = [(m.start(), m.group(1)) for m in SECTION_HEAD_RE.finditer(body)]
    for i, (pos, name) in enumerate(idx):
        end = idx[i + 1][0] if i + 1 < len(idx) else len(body)
        seg = body[pos:end]
        counts[head_key(name)] = len(re.findall(r"(?m)^\s*\d{1,2}\.\s*\S", seg))
    return counts


def build_from_pdf(doc, body_old: str, head: str, title: str, kind: str,
                   allowed_lost: set[str] | None = None) -> tuple[str, list[str]]:
    """从 PDF 重建一份文件的正文。kind ∈ {'question', 'answer'}。

    若重建会丢掉「非水印」的汉字（说明书眉/页码/版面判断有误），则**回退**为只做
    版面清洗，并报警——宁可保留旧文本，也不静默丢内容。
    """
    pages = parse_source_pages(head)
    if not pages:
        return clean_layout(body_old), ["未找到来源页码，未重建（仅清洗）"]
    sections, lines = pdf_lines(doc, pages[0], pages[1], title, track_sections=(kind == "answer"))
    if kind == "answer":
        parts = []
        for heading, answers in sections:
            parts.append(f"## {heading}\n")
            parts.append("\n".join(f"{i}. {a}" for i, a in enumerate(answers, 1)) + "\n")
        body = "\n".join(parts)
        body += "\n" + join_prose(lines)
    else:
        body = join_prose(lines)
    body = clean_layout(body)
    lost = cjk_set(scrub_old(body_old, title)) - cjk_set(body)
    gained = cjk_set(body) - cjk_set(scrub_old(body_old, title))
    notes = []
    if allowed_lost is not None and (lost - allowed_lost):
        notes.append(f"⚠️ 重建会丢正字 {''.join(sorted(lost - allowed_lost))}，已回退为仅清洗")
        fallback = clean_layout(body_old)
        return fallback, notes
    if lost:
        notes.append(f"旧有新无的字：{''.join(sorted(lost))}")
    if gained:
        notes.append(f"新有旧无的字：{''.join(sorted(gained))}")
    return body, notes


def run(apply: bool):
    if not PDF.exists():
        print(f"❌ 找不到 PDF：{PDF}")
        return 1
    import fitz  # 惰性导入：check-md 模式不走这里，无需 PDF 依赖
    doc = fitz.open(PDF)
    q_files = sorted(QA_DIR.glob("*-题目.md"))
    a_index = {f.name.replace("-答案.md", ""): f for f in QA_DIR.glob("*-答案.md")}

    if apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = QA_DIR / f".bak-{stamp}"
        backup.mkdir(parents=True)
        for f in QA_DIR.glob("*.md"):
            shutil.copy2(f, backup / f.name)
        print(f"已备份 → {backup.relative_to(ROOT)}\n")

    problems, report = [], []
    junk = junk_chars(doc)
    # 书眉/页脚里的字（单元练习/习题集/期末模拟卷）会被合法删掉
    allowed = junk | set("习练集总元期末模拟卷")
    for qf in q_files:
        key = qf.name.replace("-题目.md", "")
        title = unit_title_from_name(qf.name)
        qhead, qold = split_head(qf.read_text(encoding="utf-8"))
        qnew, qnotes = build_from_pdf(doc, qold, qhead, title, "question", allowed)
        counts = count_questions(qnew)
        if apply:
            qf.write_text(qhead.rstrip("\n") + "\n\n" + qnew, encoding="utf-8")
        lines = [f"== {title}", f"   题目题号数：{counts or '（无选择题）'}"]
        lines += [f"   {n}" for n in qnotes]

        af = a_index.get(key)
        if af:
            ahead, aold = split_head(af.read_text(encoding="utf-8"))
            anew, anotes = build_from_pdf(doc, aold, ahead, title, "answer", allowed)
            if apply:
                af.write_text(ahead.rstrip("\n") + "\n\n" + anew, encoding="utf-8")
            exp = {}
            for m in re.finditer(r"(?m)^##\s*(.+)\n\n((?:\d+\.\s*[A-D]+\s*\n)+)", anew):
                exp[head_key(m.group(1))] = len(re.findall(r"(?m)^\d+\.", m.group(2)))
            lines.append("   答案条数：" + "、".join(f"{k} {v}" for k, v in exp.items()))
            for name, n in counts.items():
                got = exp.get(head_key(name))
                if got is not None and got != n:
                    problems.append(f"{title}：{name} 题目 {n} 题 vs 答案 {got} 条 ❗")
            if len(exp) != 2:
                problems.append(f"{title}：选择题大题只识别出 {len(exp)} 个（应为 2）❗")
            # 选项完整性 + 答案落点校验
            ans_map = {}
            for m in re.finditer(r"(?m)^##\s*(.+)\n\n((?:\d+\.\s*[A-D]+\s*\n)+)", anew):
                ans_map[head_key(m.group(1))] = re.findall(r"(?m)^\d+\.\s*([A-D]+)", m.group(2))
            problems += [f"{title}：{p}" for p in check_option_integrity(qnew, ans_map)]
            lines += [f"   {n}" for n in anotes]
        else:
            lines.append("   答案：无（附加作业，无参考答案）")
        report.append("\n".join(lines))

    print("\n".join(report))
    print()
    if problems:
        print("⚠️ 需人工核对：")
        for p in problems:
            print("   -", p)
    else:
        print("✅ 16 个单元：题目题号数 = 答案条数；汉字集合差仅为水印杂字。")
    doc.close()
    return 0


def run_check_md() -> int:
    """纯 md 对账（无 PDF/第三方依赖）：不重建，直接读盘上题目/答案 md 做一致性校验。

    校验项与 report 模式重建后的对账逻辑一致，但不依赖 fitz：
      ① 题目题号数 vs 答案条数（单选/多选分开）
      ② 选择题大题是否恰好识别出 2 个（单选 + 多选）
      ③ 每题选项 A–D 连续、无重复，答案字母落在选项内
    用于判分体系出错时的第一道自救：换 Python 环境 / 原 PDF 不在位也能跑。
    """
    q_files = sorted(QA_DIR.glob("*-题目.md"))
    a_index = {f.name.replace("-答案.md", ""): f for f in QA_DIR.glob("*-答案.md")}

    problems: list[str] = []
    report: list[str] = []
    for qf in q_files:
        key = qf.name.replace("-题目.md", "")
        title = unit_title_from_name(qf.name)
        _qhead, qbody = split_head(qf.read_text(encoding="utf-8"))
        counts = count_questions(qbody)
        lines = [f"== {title}", f"   题目题号数：{counts or '（无选择题）'}"]

        af = a_index.get(key)
        if af:
            _ahead, abody = split_head(af.read_text(encoding="utf-8"))
            exp = {}
            for m in re.finditer(r"(?m)^##\s*(.+)\n\n((?:\d+\.\s*[A-D]+\s*\n)+)", abody):
                exp[head_key(m.group(1))] = len(re.findall(r"(?m)^\d+\.", m.group(2)))
            lines.append("   答案条数：" + "、".join(f"{k} {v}" for k, v in exp.items()))
            for name, n in counts.items():
                got = exp.get(head_key(name))
                if got is not None and got != n:
                    problems.append(f"{title}：{name} 题目 {n} 题 vs 答案 {got} 条 ❗")
            if len(exp) != 2:
                problems.append(f"{title}：选择题大题只识别出 {len(exp)} 个（应为 2）❗")
            ans_map = {}
            for m in re.finditer(r"(?m)^##\s*(.+)\n\n((?:\d+\.\s*[A-D]+\s*\n)+)", abody):
                ans_map[head_key(m.group(1))] = re.findall(r"(?m)^\d+\.\s*([A-D]+)", m.group(2))
            problems += [f"{title}：{p}" for p in check_option_integrity(qbody, ans_map)]
        else:
            lines.append("   答案：无（附加作业，无参考答案）")
        report.append("\n".join(lines))

    print("\n".join(report))
    print()
    if problems:
        print("⚠️ 需人工核对：")
        for p in problems:
            print("   -", p)
    else:
        print("✅ 全部单元：题目题号数 = 答案条数；选项 A–D 连续；答案落点合法。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["check-md", "report", "apply"],
                    help="check-md=纯 md 对账（无 PDF 依赖），report=只读报告（PDF 重建比对），apply=写入")
    args = ap.parse_args()
    if args.mode == "check-md":
        return run_check_md()
    return run(apply=args.mode == "apply")


if __name__ == "__main__":
    sys.exit(main())
