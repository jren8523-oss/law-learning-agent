# -*- coding: utf-8 -*-
"""
刘家安民法基础课笔记（57 讲）—— PDF → 结构化 markdown 提取器 v2（几何驱动）

相对 v1（纯文本行拼凑）的改进：
  1. 用行 bbox 右边界判断「段末/续行」，把 PDF 硬换行合并成真正的段落；
  2. 用字体+字号+文本模式识别标题层级（黑体=节，楷体=（一），仿宋/数字=1.，①=子目）；
  3. 识别上标脚注标记（6pt 数字）与页脚注释块（9pt），统一转成 markdown [^n] + 文末「注释」；
  4. 自动剔除页眉页脚、渠道水印、重复样板行；
  5. 文本层乱码的页面（如第 59 讲 ToUnicode 错位）自动按字体偏移解码；
  6. 无文本层的图片页（如第 48 讲）自动 OCR（rapidocr_onnxruntime）；
  7. 同一行内被切成多块的长距离片段（流程图）用「→」连接。

用法：
  python tools/extract_liujiaan.py                # 全部讲次
  python tools/extract_liujiaan.py --only 1 48 59 # 只处理指定讲次（调试）
  python tools/extract_liujiaan.py --no-readme    # 不重建索引
输出：
  kb/参考讲义/刘家安民法基础课/NN-第X讲.md
  kb/参考讲义/刘家安民法基础课/README.md（讲次索引 + 教材章节映射 + 统计）
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(r"D:\法学\民商法\民法-刘家安\2020刘家安民法基础课笔记")
OUT_DIR = ROOT / "kb" / "参考讲义" / "刘家安民法基础课"
INDEX_OUT = OUT_DIR / "README.md"

# ---------------- 乱码解码（第 59 讲等 ToUnicode 错位的分档字体） ----------------
CJK_OFF = {"HYShuSongErKW": 0x30FE, "HYKaiTiKW": 0x30FE, "HYZhongHeiKW": 0x30FE,
           "HYZhongDengXianKW": 0x30FE, "FZFSK": 0x4ACB}
DIGIT_OFF = {"HYShuSongErKW": 0x1E, "HYKaiTiKW": 0x1E, "HYZhongHeiKW": 0x1E,
             "HYZhongDengXianKW": 0x1E, "FZFSK": 0x1F}
PUNCT = {
    "HYShuSongErKW": {"澱": "，", "ȿ": "。", "Ⱦ": "、", "Ɇ": "《", "ɇ": "》", "Ĉ": "“", "ĉ": "”",
                      "澭": "（", "澮": "）", "澿": "：", "ă": "—", "激": "；", "濄": "？",
                      "Ɍ": "【", "ɍ": "】"},
    "HYKaiTiKW": {"澱": "，", "ȿ": "。", "Ⱦ": "、", "Ɇ": "《", "ɇ": "》", "Ĉ": "“", "ĉ": "”",
                  "澭": "（", "澮": "）", "澿": "：", "ă": "—", "激": "；", "濄": "？",
                  "Ɍ": "【", "ɍ": "】"},
    "HYZhongHeiKW": {"澱": "，", "ȿ": "。", "Ⱦ": "、", "Ɇ": "《", "ɇ": "》", "Ĉ": "“", "ĉ": "”",
                     "澭": "（", "澮": "）", "澿": "：", "ă": "—", "激": "；", "濄": "？",
                     "Ɍ": "【", "ɍ": "】"},
    "FZFSK": {"喙": "，", "ȩ": "。", "Ȩ": "、", "喧": "：", "喎": "！", "ĉ": "“", "Ċ": "”",
              "喕": "？", "喖": "？", "喬": "？", "Č": "……", "Ⱦ": "、", "Ɇ": "《", "ɇ": "》"},
}
IDENTITY_FONTS = ("MicrosoftYaHei", "SimSun", "HelveticaNeue", "Cambria", "Calibri")
TYPICAL = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff65\u2014\u2018-\u201d\u2026"
                     r"\u3400-\u4dbfA-Za-z0-9\s]")
NOISE_PAT = [r"QQ\s*群", r"qq群", r"微信", r"公众号", r"如有侵权", r"联系删除", r"独家微信",
             r"页共", r"二维码", r"2020\s*年刘家安CCtalk", r"家安民法课堂笔记小组出品", r"^©",
             r"^信\d", r"^[0-9A-Za-z]{4,}$", r"^[\d\s]{1,8}$", r"招生简章", r"客服", r"网盘",
             r"vip", r"VIP", r"报名", r"分享群", r"法考辅导", r"课程资料", r"内部课程必加"]
NOISE_RE = [re.compile(p) for p in NOISE_PAT]
WATERMARK_RE = re.compile(r"课程及纸质版联系|独家微信|微信公众号?【[^】]*】|21\s*法考[^。，]*")
OCR_CACHE = ROOT / "tools" / "_ocr_cache.json"
AD_KEYWORDS = ["招生简章", "VIP", "报名", "网盘", "客服", "微信", "QQ", "付费", "分享群",
               "课程资料", "法考辅导", "倒卖", "押题", "一研为定", "果果考资", "联系购买",
               "复习备考", "主观题考试", "倍受往届学员", "一手资料"]
AD_THRESHOLD = 2

H_CN = re.compile(r"^[一二三四五六七八九十]+、")
H_PAREN_CN = re.compile(r"^（[一二三四五六七八九十]+）")
H_NUM = re.compile(r"^\d{1,2}\.\s*\S")
H_PAREN_NUM = re.compile(r"^（\d{1,2}）")
H_CIRCLE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]")
FOOTNOTE_START = re.compile(r"^\d{1,2}[\s　]")
CHAPTER_KEYWORDS = {
    "第一章 民法概念论": ["公法与私法", "私法", "平等主体", "民法调整对象", "民法是私法"],
    "第二章 民法体系论": ["体系论", "总则", "物债二分", "法典编纂", "特别私法", "一般私法"],
    "第三章 民法方法论": ["解释方法", "请求权基础", "涵摄", "方法论", "法律漏洞", "文义解释"],
    "第四章 自然人": ["权利能力", "行为能力", "监护", "宣告失踪", "宣告死亡", "胎儿", "住所"],
    "第五章 法人": ["法人", "社团", "财团", "法定代表人", "法人人格"],
    "第六章 非法人组织": ["非法人组织", "合伙", "无限责任"],
    "第七章 物和其他权利客体": ["不动产", "动产", "主物", "从物", "孳息", "权利客体", "无体物"],
    "第八章 权利变动概述": ["权利变动", "法律事实", "民事法律关系"],
    "第九章 法律行为与意思表示": ["意思表示", "表示主义", "意思主义", "法律行为"],
    "第十章 法律行为的成立与生效": ["成立要件", "生效要件", "成立与生效", "附条件", "附期限"],
    "第十一章 法律行为的效力障碍": ["无效", "可撤销", "效力待定", "欺诈", "胁迫", "重大误解", "显失公平"],
    "第十二章 法律行为的归属": ["代理", "表见代理", "无权代理", "委托代理"],
    "第十三章 权利救济": ["民事责任", "损害赔偿", "正当防卫", "紧急避险", "自助行为"],
    "第十四章 权利的时间维度": ["诉讼时效", "除斥期间", "取得时效"],
    "第十五章 期间与期日": ["期间", "期日", "起算"],
}


def font_family(font: str) -> str:
    name = font.split("+")[-1]
    for key in CJK_OFF:
        if name.startswith(key):
            return key
    return name


# 候选偏移兜底值（实际偏移由 calibrate_offsets 按文档标定）
OFFSET_SCHEMES = (0x30FE, -0x30FE, 0x4ACB, -0x4ACB, 0)


def decode_char(ch: str, fam: str, off: int) -> str:
    o = ord(ch)
    if o < 0x20:
        r = o + DIGIT_OFF.get(fam, 0x1E)
        return chr(r) if 0x20 <= r <= 0x7E else ch
    if fam not in CJK_OFF or off == 0:
        return ch
    if off > 0 and ch in PUNCT.get(fam, {}):
        return PUNCT[fam][ch]
    r = o + off
    return chr(r) if 0x3400 <= r <= 0x9FFF else ch


_VOCAB_FILE = ROOT / "tools" / "_common_chars.txt"
_VOCAB: set[str] | None = None


def vocab() -> set[str]:
    """常用字表（冻结在 tools/_common_chars.txt）。

    不能拿刘家安笔记原件建表——55/59 讲本身就是乱码，会把乱码字当常用字。
    """
    global _VOCAB
    if _VOCAB is None:
        if _VOCAB_FILE.exists():
            _VOCAB = set(_VOCAB_FILE.read_text(encoding="utf-8"))
        else:
            counts: Counter = Counter()
            for f in (ROOT / "kb").rglob("*.md"):
                if "参考讲义" in str(f):      # 笔记原件可能有乱码，不参与
                    continue
                counts.update(f.read_text(encoding="utf-8"))
            _VOCAB = {c for c, n in counts.items() if n >= 5}
            _VOCAB_FILE.write_text("".join(sorted(_VOCAB)), encoding="utf-8")
    return _VOCAB


def top_chars(n: int = 60) -> list[str]:
    """语料中的高频汉字（用于锚点法标定偏移）。"""
    global _TOP
    try:
        return _TOP
    except NameError:
        pass
    counts: Counter = Counter()
    for f in (ROOT / "kb").rglob("*.md"):
        if "参考讲义" in str(f):
            continue
        counts.update(f.read_text(encoding="utf-8"))
    _TOP = [c for c, _ in counts.most_common(3000) if "\u4e00" <= c <= "\u9fff"][:n]
    return _TOP


def coverage(sample: str, off: int) -> float:
    v = vocab()
    good = 0
    for ch in sample:
        r = ord(ch) + off
        dec = chr(r) if 0x3400 <= r <= 0x9FFF else ch
        good += 1 if (dec in v or dec.isascii()) else 0
    return good / max(len(sample), 1)


def calibrate_offsets(doc) -> dict[str, int]:
    """按字体子集自动标定 Unicode 偏移（锚点法：拿最高频乱码字试配最高频真字）。

    覆盖常见情形：无错位（0）、与 0x30FE/0x4ACB 同量级的正负偏移、各讲次不同的错位。
    """
    fam_chars: dict[str, list[str]] = defaultdict(list)
    for page in doc:
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type", 0) != 0:
                continue
            for ln in blk.get("lines", []):
                for sp in ln["spans"]:
                    fam = font_family(sp["font"])
                    if fam in CJK_OFF and len(fam_chars[fam]) < 500:
                        fam_chars[fam].extend(sp["text"])
    offsets: dict[str, int] = {}
    small: list[str] = []
    for fam, chars in fam_chars.items():
        sample = "".join(chars)
        base = coverage(sample, 0)
        if len(sample) < 60:            # 样本太少（如封面字体）：稍后用多数票补齐
            small.append(fam)
            offsets[fam] = 0
            continue
        if base > 0.95:
            offsets[fam] = 0
            continue
        cands = {0, 0x30FE, -0x30FE, 0x4ACB, -0x4ACB}
        top3 = [c for c, _ in Counter(sample).most_common(3)]
        for real in top_chars():
            for g in top3:
                cands.add(ord(real) - ord(g))
        best = max(cands, key=lambda o: coverage(sample, o))
        offsets[fam] = best if coverage(sample, best) > base else 0
    if small:                            # 小组样本继承文档内多数偏移
        votes = Counter(o for f, o in offsets.items() if f not in small and o)
        fallback = votes.most_common(1)[0][0] if votes else 0
        for fam in small:
            offsets[fam] = fallback
    return offsets


def garbled_ratio(text: str) -> float:
    t = text.replace("\n", "")
    if not t:
        return 0.0
    v = vocab()
    good = sum(1 for c in t if c in v or c.isascii() or c in "。，、；：「」《》？！—…（）　→【】·")
    return 1 - good / len(t)


PUA_RE = re.compile(r"[\ue000-\uf8ff\u2600-\u27bf\u2b00-\u2bff]")


def sanitize(text: str) -> str:
    """去掉 PDF 里的装饰性符号字形（私用区/U+F076 之类）与尾部空白。"""
    return PUA_RE.sub("", text).strip()


# ---------------- 行结构 ----------------
class Line:
    __slots__ = ("text", "size", "max_size", "min_size", "fonts", "x0", "y0", "x1", "y1", "page")

    def __init__(self, text, sizes, fonts, bbox, page):
        self.text = text
        self.min_size = min(sizes) if sizes else 0
        self.max_size = max(sizes) if sizes else 0
        self.size = self.max_size
        self.fonts = fonts
        self.x0, self.y0, self.x1, self.y1 = bbox
        self.page = page

    @property
    def is_body_size(self) -> bool:
        return self.max_size >= 11.5


def is_noise(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    return any(r.search(s) for r in NOISE_RE)


def is_ad_page(text: str) -> bool:
    return sum(1 for kw in AD_KEYWORDS if kw in text) >= AD_THRESHOLD

def _lines_from_dict(page, pno: int, offsets: dict[str, int]) -> list[Line]:
    lines: list[Line] = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type", 0) != 0:
            continue
        for ln in blk.get("lines", []):
            raw_spans = []
            for sp in ln["spans"]:
                fam = font_family(sp["font"])
                off = offsets.get(fam, 0)
                txt = "".join(decode_char(c, fam, off) for c in sp["text"])
                if txt:
                    raw_spans.append((txt, sp["size"], fam))
            if not raw_spans:
                continue
            # 上标脚注标记只在正文行（含 ≥11.5pt 字号）里识别；页脚注释行保留原数字
            is_body = max(s[1] for s in raw_spans) >= 11.5
            spans = []
            for txt, size, fam in raw_spans:
                if is_body and size < 8 and txt.strip().isdigit():
                    spans.append((f"⟦{txt.strip()}⟧", size, fam))
                else:
                    spans.append((txt, size, fam))
            text = sanitize("".join(s[0] for s in spans))
            if not text:
                continue
            sizes = [s[1] for s in spans]
            fonts = [s[2] for s in spans]
            lines.append(Line(text, sizes, fonts, ln["bbox"], pno))
    return [l for l in lines if not is_noise(l.text)]


_OCR_CACHE: dict | None = None


def ocr_page(page, pno: int, key: str) -> list[Line]:
    """OCR 单页（磁盘缓存，避免重复跑模型）。"""
    global _OCR_CACHE
    if _OCR_CACHE is None:
        _OCR_CACHE = json.loads(OCR_CACHE.read_text(encoding="utf-8")) if OCR_CACHE.exists() else {}
    ck = f"{key}#{pno}"
    if ck not in _OCR_CACHE:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        global _OCR
        try:
            _OCR
        except NameError:
            _OCR = RapidOCR()
        scale = min(200 / 72, 2200 / max(page.rect.width, page.rect.height, 1))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        res, _ = _OCR(img)
        _OCR_CACHE[ck] = [[[round(c * 72 / 200, 1) for c in item[0][0]][:2], item[1]] for item in (res or [])]
        OCR_CACHE.write_text(json.dumps(_OCR_CACHE, ensure_ascii=False), encoding="utf-8")
    out = []
    for (x, y), text in _OCR_CACHE[ck]:
        t = sanitize(WATERMARK_RE.sub("", text))
        if not t or is_noise(t):
            continue
        out.append(Line(t, [12.0], ["OCR"], (x, y, x + 12.2 * len(t), y + 14), pno))
    return out


def collect_lines(page, pno: int, use_ocr: bool, key: str, offsets: dict[str, int]) -> tuple[list[Line], bool]:
    """返回（行列表, 是否用了 OCR）。先按标定偏移解码，仍乱码则回退 OCR。"""
    lines = _lines_from_dict(page, pno, offsets)
    ratio = garbled_ratio("".join(l.text for l in lines)) if lines else 1.0
    if not use_ocr or ratio <= 0.08:
        return lines, False
    return ocr_page(page, pno, key), True


def merge_fragments(lines: list[Line]) -> list[Line]:
    """同一 y 带内的碎片按 x 顺序合并为视觉行；长距离碎片用「→」连接（流程图/表头）。

    不能按 y 取整排序：PDF 会把上标脚注标记渲染成 y 略有差异的独立碎片，
    排序时不按 x 归位会把句子打乱。
    """
    out: list[Line] = []
    cluster: list[Line] = []
    for ln in sorted(lines, key=lambda l: l.y0):
        if cluster and ln.y0 - cluster[0].y0 > 3:
            out.append(_merge_cluster(cluster))
            cluster = []
        cluster.append(ln)
    if cluster:
        out.append(_merge_cluster(cluster))
    return out


def _merge_cluster(cluster: list[Line]) -> Line:
    """把一个 y 带内的水平碎片合成一行；先去重复/叠加层，再按位置拼接。"""
    cluster.sort(key=lambda l: l.x0)
    if len(cluster) > 1:
        ref = max(cluster, key=lambda l: l.x1 - l.x0)
        keep: list[Line] = []
        seen: set[str] = set()
        for l in cluster:
            if l is not ref:
                duplicated = len(l.text) > 4 and l.text in ref.text          # 叠印重复层
                overlay = (l.x0 >= ref.x0 - 5 and l.x1 <= ref.x1 + 5         # 横向落入正文行内部
                           and len(l.text) <= 60 and l.min_size >= 11.5)
                if duplicated or overlay or l.text in seen:
                    continue
            seen.add(l.text)
            keep.append(l)
        cluster = keep
    head = cluster[0]
    for ln in cluster[1:]:
        gap = ln.x0 - head.x1
        joiner = "　→　" if gap > 15 else (" " if gap > 6 else "")
        if head.fonts == ["OCR"] and head.fonts == ln.fonts:
            joiner = ""
        head.text = head.text.rstrip() + joiner + ln.text.lstrip()
        head.x1 = max(head.x1, ln.x1)
        head.fonts = head.fonts + ln.fonts
        head.min_size = min(head.min_size, ln.min_size)
        head.max_size = max(head.max_size, ln.max_size)
        head.size = head.max_size
    return head


def classify(line: Line) -> tuple[str, str]:
    """返回 (kind, text)。kind ∈ heading2..heading6 / footnote / para / quote"""
    t = line.text.strip()
    fonts = "".join(line.fonts)
    hei = "SimHei" in fonts or "HYZhongHei" in fonts
    kai = "KaiTi" in fonts or "HYKaiTi" in fonts
    fang = "FangSong" in fonts or "FZFSK" in fonts
    if line.max_size >= 13.5 and hei:
        return "h2", t
    if hei and H_CN.match(t):
        return "h3", t
    if hei and len(t) <= 20 and not t.endswith(("。", "？", "！")):
        return "h3", t
    if H_CN.match(t):
        return "h3", t
    if H_PAREN_CN.match(t):
        return "h4", t
    if fang and H_NUM.match(t):
        return "h5", t
    if H_NUM.match(t) and len(t) <= 18 and not t.endswith(("。", "，")):
        return "h5", t
    if H_PAREN_NUM.match(t):
        return "h6", t
    if H_CIRCLE.match(t):
        return "h6", t
    return "para", t


def build_page(lines: list[Line], page_h: float) -> tuple[list[Line], list[Line]]:
    """把一页的行拆成（正文行, 页脚注释区行）。

    判据：页脚注释区 = 最后一个 ≥11.5pt 正文行之后的全部小字号行（不受固定 y 阈值影响）。
    """
    lines = [l for l in merge_fragments(lines) if 40 <= l.y0 <= page_h - 70]
    last_body = -1
    for i, ln in enumerate(lines):
        if ln.is_body_size:
            last_body = i
    body = lines[:last_body + 1]
    foot = lines[last_body + 1:]
    return body, foot


def collect_notes(pages_foot: list[list[Line]]) -> dict[int, str]:
    """把各页页脚注释行拼成 {原编号: 注释文本}（支持跨页续行、应付页脚缺编号的情况）。"""
    notes: list[list] = []          # [num or None, text]
    last_num = 0
    complete = "。！？”」））"
    for foot in pages_foot:
        for ln in foot:
            t = ln.text.strip()
            if not t:
                continue
            m = re.match(r"^(\d{1,2})[\s　、.．]?", t)
            if m and int(m.group(1)) <= 40 and len(t) - m.end() > 0:
                last_num = int(m.group(1))
                notes.append([last_num, t[m.end():].strip()])
            elif notes and notes[-1][1][-1:] not in complete:
                notes[-1][1] += t          # 上一条未写完 → 续行
            else:
                last_num += 1              # 页脚漏印编号 → 按顺序补号
                notes.append([last_num, t])
    out: dict[int, str] = {}
    for num, txt in notes:
        out[num] = (out.get(num, "") + txt).strip()
    return out


def normalize(text: str) -> str:
    """排版规范化：数字与汉字间补空格、全角标点、引号转「」。"""
    t = text
    t = re.sub(r"(?<=[0-9])(?=[\u4e00-\u9fff])", " ", t)
    t = re.sub(r"(?<=[\u4e00-\u9fff])(?=[0-9])", " ", t)
    t = re.sub(r"(?<=[\u4e00-\u9fff\uff09\u300b]):(?=[\u4e00-\u9fff\u300a])", "：", t)
    t = re.sub(r"([\u4e00-\u9fff\u3002\uff0c]),(?=[\u4e00-\u9fff])", r"\1，", t)
    t = t.replace(" ,", "，").replace(" ;", "；").replace(" (", "（").replace(") ", "）")
    t = t.replace("“", "「").replace("”", "」")
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def assemble(body: list[Line], note_texts: dict[int, str], edges: dict[int, float]) -> tuple[str, list[str]]:
    """按每页版心右边界合并段落；上标脚注标记转 [^n]；返回（正文 markdown, 注释列表）"""
    order: list[int] = []                # 原编号按正文出现顺序

    def note_ref(num: int) -> str:
        if num not in order:
            order.append(num)
        return f"[^{order.index(num) + 1}]"

    out: list[tuple[str, str]] = []      # (kind, text)
    cur_kind, cur_text = None, ""
    marker = re.compile(r"⟦(\d{1,2})⟧")
    for i, ln in enumerate(body):
        kind, text = classify(ln)
        text = marker.sub(lambda m: note_ref(int(m.group(1))), text)
        if kind != "para":
            if cur_text:
                out.append((cur_kind, cur_text))
                cur_text = ""
            out.append((kind, text))
            cur_kind = kind
            continue
        if cur_text:
            cur_text += text
        else:
            cur_kind, cur_text = "para", text
        # 段末判断：本行右边界明显短于本页版心右边界 → 段落结束
        short = ln.x1 < edges.get(ln.page, 511) - 8
        if short and i + 1 < len(body):
            nxt = body[i + 1].text.strip()
            # 行尾是数字/顿号/引号/左括号，或下一行以右括号类开头 → 断言是段中（PDF 排版导致的假段末）
            if (text and text[-1] in "0123456789、，,（(「“《") or (nxt and nxt[0] in "）)】」”》"):
                short = False
        if short:
            out.append((cur_kind, cur_text))
            cur_text = ""
    if cur_text:
        out.append((cur_kind, cur_text))

    md: list[str] = []
    for kind, text in out:
        if kind == "para" and len(text) >= 60 and text.startswith("“") and text.rstrip().endswith("”"):
            md.append(f"> {text}\n")
        elif kind == "para":
            md.append(text + "\n")
        else:
            level = {"h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}[kind]
            text = re.sub(r"^(第[一二三四五六七八九十]+讲)(?=\S)", r"\1 ", text)
            text = normalize(text)
            md.append(f"{level} {text}\n")
    body_md = re.sub(r"\n{3,}", "\n\n", "\n".join(md))
    body_md = "\n".join(normalize(l) if l and not l.startswith("#") else l for l in body_md.split("\n"))

    notes_out = []
    missing = [num for num in order if num not in note_texts]
    unused = [n for n in sorted(note_texts) if n not in order]
    used_nums = set(order)
    if missing and len(unused) == len(missing):      # 编号体系不一致 → 按顺序对位
        for num, alt in zip(missing, unused):
            note_texts[num] = note_texts[alt]
            used_nums.add(alt)
    for num in order:
        notes_out.append(note_texts.get(num, "（原 PDF 未提供该注释文本，可能为图片截图）"))
    return body_md, notes_out


def lecture_number(name: str) -> int:
    m = re.search(r"(\d+)\s*【", name)
    return int(m.group(1)) if m else 0


def cn_num(n: int) -> str:
    d = "零一二三四五六七八九"
    if n < 10:
        return d[n]
    if n < 20:
        return "十" + (d[n % 10] if n % 10 else "")
    return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")


def convert(num: int, path: Path) -> dict:
    doc = fitz.open(path)
    offsets = calibrate_offsets(doc)
    page_blocks: list[list[Line]] = []
    feet: list[list[Line]] = []
    edges: dict[int, float] = {}
    ad_pages = ocr_pages = 0
    cover_lines: list[str] = []
    for pno, page in enumerate(doc, 1):
        lines, used_ocr = collect_lines(page, pno, use_ocr=True, key=path.name, offsets=offsets)
        if is_ad_page("".join(l.text for l in lines)):
            ad_pages += 1
            continue
        ocr_pages += int(used_ocr)
        if not lines:
            continue
        body, foot = build_page(lines, page.rect.height)
        if pno == 1:                  # 封面页：只取标题，不入正文
            cover_lines = [l.text.strip() for l in body]
            continue
        if body:
            xs = sorted(l.x1 for l in body if l.is_body_size)
            top = xs[-max(1, len(xs) // 5):]           # 取最靠右的 20% 行的中位数，抗离群值
            edges[pno] = top[len(top) // 2] - 4
        if not body and not foot:
            continue
        page_blocks.append(body)
        feet.append(foot)
    doc.close()

    flat = [ln for blk in page_blocks for ln in blk]
    md, note_texts = assemble(flat, collect_notes(feet), edges)

    # 封面标题：取「课堂笔记（X）」行，前面若紧跟「…民法基础课」则拼上
    cover_title = None
    for i, t in enumerate(cover_lines):
        if "课堂笔记" in t:
            cover_title = t
            if i and "民法基础课" in cover_lines[i - 1]:
                cover_title = f"{cover_lines[i - 1]} {t}"
            break

    title = f"# 2020 年刘家安民法基础课 课堂笔记（{cn_num(num)}）"
    cover_note = ""
    if cover_title and re.sub(r"[（(]|[)）]|\s", "", cover_title) not in \
            re.sub(r"[（(]|[)）]|\s", "", title):
        cover_note = f"（原封面标题：{cover_title}）"
    ocr_note = f"其中 {ocr_pages} 页原 PDF 无可靠文本层，由 OCR 识别重建。" if ocr_pages else ""
    head = [
        title,
        "",
        f"> 来源：{path.name}（{len(page_blocks)} 页有效内容，跳过 {ad_pages} 页广告）"
        f"· 家安民法课堂笔记小组 整理{cover_note}",
        "> 整理说明：已剔除页眉页脚与渠道水印（原文档页眉含推广群号/公众号等流传标注，非课程内容）；"
        "PDF 硬换行已按版心合并为段落；页脚法条注释统一转为本文件末尾「注释」；数字与汉字间补空格、引号统一为「」"
        f"。{ocr_note}",
        "",
    ]
    parts = ["\n".join(head), "", md.rstrip(), ""]
    if note_texts:
        parts += ["---", "", "## 注释", ""]
        for i, t in enumerate(note_texts, 1):
            parts.append(f"[^{i}]: {normalize(t)}")
        parts.append("")
    text = "\n".join(parts).rstrip() + "\n"
    (OUT_DIR / f"{num:02d}-第{num}讲.md").write_text(text, encoding="utf-8")
    return {"num": num, "pages": len(page_blocks), "ad": ad_pages, "ocr": ocr_pages,
            "notes": len(note_texts), "chars": len(text), "body": md, "file": f"{num:02d}-第{num}讲.md",
            "title": (cover_title or f"第{num}讲")}

def main() -> None:
    only = set()
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        for a in sys.argv[i + 1:]:
            if a.isdigit():
                only.add(int(a))
            else:
                break
    pdfs = sorted(SRC_DIR.glob("*.pdf"))
    by_num: dict[int, Path] = {}
    for p in pdfs:
        n = lecture_number(p.name)
        by_num[n] = max(by_num.get(n, p), p, key=lambda x: x.stat().st_size)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for num, p in sorted(by_num.items()):
        if only and num not in only:
            continue
        info = convert(num, p)
        rows.append(info)
        print(f"  {info['file']:<16} 页={info['pages']:<3} 广告={info['ad']:<2} OCR={info['ocr']:<3} "
              f"注释={info['notes']:<3} 字符={info['chars']:<6} {info['title']}")
    if "--no-readme" in sys.argv or only:
        return

    # 索引
    lines = ["# 刘家安民法基础课笔记 — 索引", "",
             "> 2020 年刘家安 CCtalk 民法基础课随堂笔记（打字版，入库 57 讲：第 1–56 讲 + 第 59 讲，第 57、58 讲无笔记）。",
             "> 定位：杨代雄《民法总论》的**辅助讲解材料**——教材讲不透时按章查讲次，读对应 md。",
             "> 由 `tools/extract_liujiaan.py` 从原 PDF 几何提取：段落已合并、标题已分级、页脚法条注释已转文末「注释」、页眉水印已剔除。",
             "", "## 讲次索引", "", "| 文件 | 有效页 | 页脚注释 | 备注 |", "|---|---|---|---|"]
    for info in rows:
        note = []
        if info["ocr"]:
            note.append(f"{info['ocr']} 页 OCR 重建")
        if info["ad"]:
            note.append(f"跳过 {info['ad']} 页广告")
        lines.append(f"| {info['file']} | {info['pages']} | {info['notes']} | {'；'.join(note)} |")
    lines += ["", "## 与教材章节的映射（按关键词密度排序，取最相关前 5 讲）", ""]
    for ch, kws in CHAPTER_KEYWORDS.items():
        scored = []
        for info in rows:
            s = sum(info["body"].count(kw) for kw in kws)
            if s:
                scored.append((s, info["num"]))
        scored.sort(reverse=True)
        top = ", ".join(f"第{n}讲" for _s, n in scored[:5])
        lines.append(f"- **{ch}** → {top if scored else '（无匹配）'}")
    lines += [
        "", "## 维护命令", "",
        "- `python tools/extract_liujiaan.py`：从源 PDF 重提全库（几何版式 → 合并段落、标题分级、"
        "页脚注释转文末「注释」；乱码页自动标定字体偏移解码；无文本层页自动 OCR）",
        "- `python tools/extract_liujiaan.py --only 1 55`：只重跑指定讲次（调试用，不重建本索引）",
        "- `python tools/qc_liujiaan.py`：与旧版提取件对比 + 残留水印/碎段/超长段检查",
        "- `python tools/qc_liujiaan_residual.py`：扫描残留乱码/低常用字覆盖率行",
        "- `_原始提取/`：旧版（逐行拼接）提取件备份，供对照与回滚；`tools/_ocr_cache.json` 为 OCR 缓存",
    ]
    tail = ""
    INDEX_OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"\n索引已更新：{INDEX_OUT}")


if __name__ == "__main__":
    main()
