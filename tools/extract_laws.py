# -*- coding: utf-8 -*-
"""
法条库提取器：从 inbox 的 docx 提取《民法典》全文与司法解释 → kb/laws/*.md

用法：
    python tools/extract_laws.py detect                 # 只打印结构与边界探测
    python tools/extract_laws.py extract                # 写入 kb/laws/

来源：
    material/inbox/民法典及相关司法解释汇编.docx        （民法典全文 + 配套解释）
    material/inbox/最高人民法院关于适用《中华人民共和国民法典》总则编若干问题的解释.docx
    material/inbox/合同编通则司法解释.docx

设计原则：
- 只从 docx 原文提取，不改条文一个字；款/项按原文段落原样保留。
- 民法典全文按「编 / 分编 / 章 / 条」分层转 markdown。
- 配套解释单独成文件，不进民法典正文。
"""
import re
import sys
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "material" / "inbox"
OUT = ROOT / "kb" / "laws"

MINFA_DOCX = INBOX / "民法典及相关司法解释汇编.docx"
ZONGBIAN_DOCX = INBOX / "最高人民法院关于适用《中华人民共和国民法典》总则编若干问题的解释.docx"
HETONGBIAN_DOCX = INBOX / "合同编通则司法解释.docx"

# ────────────────────────────── docx 文本抽取 ──────────────────────────────


def docx_paras(path: Path) -> list[str]:
    """抽取 docx 段落文本（去掉域代码，表格单元格按段落顺序展开）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"<w:instrText[^>]*>.*?</w:instrText>", "", xml)
    xml = re.sub(r"<w:fldChar[^>]*>.*?</w:fldChar>", "", xml)
    out = []
    for p in re.split(r"</w:p>", xml):
        line = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p)).strip()
        out.append(line)
    return out


def clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


# 中文数字法条号 / 编 / 章 / 分编
TIAO_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)条(?:\s*(.*))?$")
BIAN_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)编(?:\s*(.*))?$")
FENBIAN_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)分编(?:\s*(.*))?$")
ZHANG_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)章(?:\s*(.*))?$")
JIE_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)节(?:\s*(.*))?$")
FUZE_RE = re.compile(r"^附\s*则$")


def structure_minfa(paras: list[str]) -> list[str]:
    """把民法典正文段落转成 markdown 行。"""
    # 定位正文起止：正文从「第一条」真实条文之前的最后一个「第一编 总则」开始
    # （目录里也有「第一编 总则」，但目录不列到「第一条」层级，故以第一条为锚）
    first_art = next((i for i, p in enumerate(paras) if clean_title(p).startswith("第一条")), None)
    end = next((i for i, p in enumerate(paras) if "第一千二百六十条" in p), None)
    if first_art is None or end is None:
        raise RuntimeError("未定位到民法典正文边界")
    start = max(i for i, p in enumerate(paras) if i < first_art and p.startswith("第一编") and "总" in p)
    body = paras[start:end + 1]

    out: list[str] = []
    for raw in body:
        s = clean_title(raw)
        if not s:
            out.append("")
            continue
        m = FENBIAN_RE.match(s)
        if m:
            out.append(f"### 第{m.group(1)}分编 {m.group(2) or ''}".strip())
            continue
        m = BIAN_RE.match(s)
        if m:
            out.append(f"## 第{m.group(1)}编 {m.group(2) or ''}".strip())
            continue
        m = ZHANG_RE.match(s)
        if m:
            out.append(f"#### 第{m.group(1)}章 {m.group(2) or ''}".strip())
            continue
        m = JIE_RE.match(s)
        if m:
            out.append(f"##### 第{m.group(1)}节 {m.group(2) or ''}".strip())
            continue
        if FUZE_RE.match(s):
            out.append("## 附则")
            continue
        m = TIAO_RE.match(s)
        if m:
            body_txt = (m.group(2) or "").strip()
            out.append(f"**第{m.group(1)}条** {body_txt}".strip())
            continue
        # 款 / 项 / 其他正文行
        out.append(s)
    # 压掉连续空行
    lines = []
    blank = False
    for l in out:
        if not l:
            if not blank:
                lines.append("")
            blank = True
        else:
            lines.append(l)
            blank = False
    return lines


def structure_explanation(paras: list[str]) -> list[str]:
    """司法解释：保留「X、部分」标题与条文，条加粗。"""
    out: list[str] = []
    for raw in paras:
        s = clean_title(raw)
        if not s:
            out.append("")
            continue
        m = TIAO_RE.match(s)
        if m:
            out.append(f"**第{m.group(1)}条** {m.group(2) or ''}".strip())
            continue
        if re.match(r"^[一二三四五六七八九十]+、", s):
            out.append(f"### {s}")
            continue
        out.append(s)
    lines = []
    blank = False
    for l in out:
        if not l:
            if not blank:
                lines.append("")
            blank = True
        else:
            lines.append(l)
            blank = False
    return lines


# ────────────────────────────── 探测 ──────────────────────────────


def detect():
    for path, kind in [(MINFA_DOCX, "民法典"), (ZONGBIAN_DOCX, "总则编解释"), (HETONGBIAN_DOCX, "合同编通则解释")]:
        if not path.exists():
            print(f"❌ 缺文件：{path.name}")
            continue
        paras = docx_paras(path)
        print(f"== {kind} ==  {path.name}")
        print(f"   段落数 {len(paras)}，字符 {sum(len(p) for p in paras)}")
        if kind == "民法典":
            starts = [i for i, p in enumerate(paras) if p.startswith("第一编")]
            ends = [i for i, p in enumerate(paras) if "第一千二百六十条" in p]
            print(f"   第一编候选行 {starts[:6]}；第一千二百六十条行 {ends[:6]}")
        else:
            print("   前 3 行：")
            for p in paras[:3]:
                print(f"     {p[:60]!r}")
        print()


# ────────────────────────────── 写入 ──────────────────────────────


MINFA_HEADER = """# 中华人民共和国民法典

- 全称：《中华人民共和国民法典》
- 通过：2020 年 5 月 28 日第十三届全国人民代表大会第三次会议
- 施行：2021 年 1 月 1 日（同日废止《婚姻法》《继承法》《民法通则》《收养法》《担保法》《合同法》《物权法》《侵权责任法》《民法总则》）
- 结构：总则、物权、合同、人格权、婚姻家庭、继承、侵权责任七编及附则，共 1260 条
- 来源：inbox《民法典及相关司法解释汇编.docx》原文提取（未经改动）

"""


def extract():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []

    # 1. 民法典全文
    paras = docx_paras(MINFA_DOCX)
    lines = structure_minfa(paras)
    text = MINFA_HEADER + "\n".join(lines) + "\n"
    out_path = OUT / "民法典.md"
    out_path.write_text(text, encoding="utf-8")
    n_tiao = sum(1 for l in lines if l.startswith("**第") and "条**" in l)
    report.append(f"民法典.md：{n_tiao} 条，{len(text)} 字符")

    # 2. 总则编解释
    for src, name, head in [
        (ZONGBIAN_DOCX, "民法典总则编解释.md", "总则编司法解释"),
        (HETONGBIAN_DOCX, "民法典合同编通则解释.md", "合同编通则司法解释"),
    ]:
        if not src.exists():
            report.append(f"{name}：跳过（缺源文件 {src.name}）")
            continue
        paras = docx_paras(src)
        lines = structure_explanation(paras)
        body = "\n".join(lines) + "\n"
        # 去首部重复的标题行（docx 首行常与文件名重复）
        text = f"# {head}\n\n> 来源：{src.name}（法释原文提取）\n\n{body}"
        op = OUT / name
        op.write_text(text, encoding="utf-8")
        report.append(f"{name}：{len(text)} 字符")

    print("✅ 法条库已写入 kb/laws/")
    for r in report:
        print("  -", r)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["detect", "extract"])
    args = ap.parse_args()
    detect() if args.mode == "detect" else extract()


if __name__ == "__main__":
    main()
