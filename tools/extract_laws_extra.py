# -*- coding: utf-8 -*-
"""
补充法条提取器：inbox/material-laws 里的 docx → kb/laws/*.md（忠实原文，不改一个字）

用法：
  python tools/extract_laws_extra.py detect    # 只打印结构信息
  python tools/extract_laws_extra.py extract  # 写入 kb/laws/

处理三类：
  1) mrt_assembly —— 《民事诉讼法》与《民诉法解释》逐条对照讲义（【第X条】/【解释第X条】）
  2) jsi          —— 司法解释（第X条 + 续行款），元数据（发文字号/公布/施行）抽到头部
"""
import argparse
import html
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
LAWS_SRC = ROOT / "material" / "laws"
OUT = ROOT / "kb" / "laws"

FILES = [
    {
        "kind": "mrt_assembly",
        "src": ROOT / "material" / "laws" / "民事诉讼法法典汇编（民诉法·民诉法解释对照）.docx",
        "src_fallback": INBOX / "民事诉讼法法典汇编（民诉法·民诉法解释对照）.docx",
        "out": "民事诉讼法.md",
        "title": "中华人民共和国民事诉讼法（附《民诉法解释》逐条对照）",
        "source": "material/laws/民事诉讼法法典汇编（民诉法·民诉法解释对照）.docx",
    },
    {
        "kind": "jsi",
        "src": LAWS_SRC / "最高人民法院关于适用《中华人民共和国民法典》侵权责任编的解释(一).docx",
        "out": "民法典侵权责任编解释一.md",
        "title": "最高人民法院关于适用《中华人民共和国民法典》侵权责任编的解释（一）",
        "source": "material/laws/最高人民法院关于适用《中华人民共和国民法典》侵权责任编的解释(一).docx",
        "short": "侵权责任编司法解释（一）",
    },
    {
        "kind": "jsi",
        "src": LAWS_SRC / "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释(二)(2026)(FBM-CLI.3.5346800).docx",
        "out": "建设工程施工合同解释二.md",
        "title": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（二）",
        "source": "material/laws/最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释(二)(2026).docx",
        "short": "建设工程施工合同司法解释（二）",
    },
]

ART_RE = re.compile(r"^第([一二三四五六七八九十百千零〇]+)条")
HEAD_TAIL_RE = re.compile(r"([。；）])\s*(第[一二三四五六七八九十]+[编章节])\s*(\S{0,25})$")
ART_MARK_RE = re.compile(r"^【(解释)?第([一二三四五六七八九十百千零〇]+)条】\s*(.*)$")
JSI_ART_RE = re.compile(r"^(第[一二三四五六七八九十百千零〇]+条)[　\s]*(.*)$")
META_KEEP_RE = re.compile(r"^(发文字号|公布日期|施行日期|时效性)[：:]")
META_DROP_RE = re.compile(r"^(制定机关|法规类别|效力位阶|机构沿革)")
SKIP_LINE_RE = re.compile(r"^(法宝联想|中华人民共和国最高人民法院公告)$")
JUNK_SUB_RE = re.compile(
    r"^(法律法规|司法案例|法律动态|法学|期刊|专题参考|行政法规|部门规章|司法解释)\s+.*（\d+）$")
# 北大法宝导出的附录（「本篇引用的法规」/「背景资料」/答记者问 等），一律截断
CUT_STANDALONE = {"背景资料", "法规解读", "本篇引用的法规", "引用本篇的法规", "中央法规",
                   "行政法规", "部门规章", "地方法规", "司法解释", "相关法规", "相关案例", "更多"}
CUT_RE = re.compile(r"^(相关法规|相关案例|关联法规|相关论文|引用本篇|本篇引用|最高法.{0,24}答记者问)")
FAHAO_RE = re.compile(r"法释〔\d{4}〕\d+\s*号")
DATE_RE = re.compile(r"（[^）]*通过[^）]*施行[^）]*）")
HEAD_LEVEL = {"编": "##", "章": "###", "节": "####"}


def docx_paras(path: Path):
    """docx → 段落文本（剔除 rPr/pPr/域代码，兜底去残留标签）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"<w:instrText[^>]*>.*?</w:instrText>", "", xml, flags=re.S)
    xml = re.sub(r"<w:(rPr|pPr)>.*?</w:\1>", "", xml, flags=re.S)
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S):
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        txt = html.unescape(re.sub(r"<[^>]*>", "", txt))
        paras.append(txt.replace("\u3000", " ").strip())
    return [p for p in paras if p]


def split_trailing_heading(p: str):
    """把「…正文。 第二节 地域管辖」尾部的标题切出来。"""
    m = HEAD_TAIL_RE.search(p)
    if not m:
        return p, None
    return p[:m.end(1)], m.group(2)


def render_mrt_assembly(cfg, paras):
    out = [
        f"# {cfg['title']}",
        "",
        f"> 来源：`{cfg['source']}`（教学讲义原文提取，未改动一个字）",
        "> 提示：讲义所附《民诉法解释》（法释〔2022〕11 号）条文序号系对照 2021 年修正的民事诉讼法；",
        "> 2023 年第五次修正后，民事诉讼法部分条文序号（尤其涉外民事诉讼程序编）已变动，",
        "> 解释条文中的旧序号未作改写，正式引用前请核对国家法律法规数据库（flk.npc.gov.cn）。",
        "> 体例：`**第X条**` = 民事诉讼法条文；`> **〔解释第X条〕**` = 对应民诉法解释条文。",
        "",
        "## 讲义编制说明（原文）",
        "",
    ]
    di, di_done, n_law, n_jsi = 0, False, 0, 0
    for p in paras:
        if not di_done:
            out.append("> " + p)
            di += 1
            if p.startswith("五、"):
                di_done = True
                out.append("")
            continue
        head = None
        p, head = split_trailing_heading(p)
        m = ART_MARK_RE.match(p)
        if m:
            tag = ("**〔解释第%s条〕**" % m.group(2)) if m.group(1) else ("**第%s条**" % m.group(2))
            body = ("%s %s" % (tag, m.group(3))).rstrip()
            out.append(("> " + body) if m.group(1) else body)
            n_jsi += bool(m.group(1))
            n_law += (not m.group(1))
        else:
            out.append(p)
        if head:
            kind = head[-1]
            out.append("")
            out.append(f"{HEAD_LEVEL[kind]} {head}")
        out.append("")
    return out, f"法条 {n_law} 条 / 解释 {n_jsi} 条"


def render_jsi(cfg, paras):
    title_line = fahao = dates = yinyan = None
    keep_meta, arts = [], []
    started = False
    for p in paras:
        if p in CUT_STANDALONE or CUT_RE.match(p):
            break
        if SKIP_LINE_RE.match(p) or JUNK_SUB_RE.match(p) or META_DROP_RE.match(p):
            continue
        if not started and JSI_ART_RE.match(p):
            started = True
        if started:
            m = JSI_ART_RE.match(p)
            if m:
                arts.append((f"**{m.group(1)}**" + (" " + m.group(2) if m.group(2) else "")).rstrip())
            else:
                arts.append(p)
            continue
        # 头部元信息（可同时命中多条）
        if fahao is None and FAHAO_RE.search(p):
            fahao = FAHAO_RE.search(p).group(0)
        if dates is None and DATE_RE.search(p):
            dates = DATE_RE.search(p).group(0)
        if META_KEEP_RE.match(p):
            keep_meta.append(p)
            continue
        if title_line is None and p.startswith("最高人民法院关于") and len(p) > 12:
            title_line = p
            continue
        if yinyan is None and (p.startswith("为正确审理") or p.startswith("为依法")):
            yinyan = p

    out = [f"# {cfg['short']}", "", f"> 来源：`{cfg['source']}`（法释原文提取，未改动一个字）", ""]
    out.append(cfg["title"])
    if fahao:
        out.append(fahao)
    if dates:
        out.append(dates)
    elif keep_meta:
        out += keep_meta
    if yinyan:
        out.append(yinyan)
    out.append("")
    out += arts
    return out, f"条文 {sum(1 for a in arts if a.startswith('**第'))} 条"


def resolve_src(cfg):
    """源文件可已从 inbox 移到 material/laws。"""
    s = Path(cfg["src"])
    if s.exists():
        return s
    for d in (LAWS_SRC, INBOX):
        alt = d / s.name
        if alt.exists():
            return alt
    if cfg.get("src_fallback"):
        return Path(cfg["src_fallback"])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["detect", "extract"])
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    for cfg in FILES:
        if args.only and args.only not in cfg["out"]:
            continue
        if not resolve_src(cfg).exists():
            print("!! 缺源文件：", cfg["src"])
            continue
        paras = docx_paras(resolve_src(cfg))
        fn = render_mrt_assembly if cfg["kind"] == "mrt_assembly" else render_jsi
        lines, stat = fn(cfg, paras)
        text = "\n".join(lines).rstrip() + "\n"
        print("=" * 74)
        print(f"{cfg['out']}  ← {resolve_src(cfg).name}")
        print(f"  段落 {len(paras)} | {stat} | 输出 {len(text)} 字符 / {text.count(chr(10))} 行")
        if args.cmd == "extract":
            (OUT / cfg["out"]).write_text(text, encoding="utf-8")
            print(f"  → kb/laws/{cfg['out']}")


if __name__ == "__main__":
    main()
