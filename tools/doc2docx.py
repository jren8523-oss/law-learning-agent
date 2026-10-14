# -*- coding: utf-8 -*-
"""
.doc（Word 97-2003 二进制）→ .docx 转换器（走 Word COM，晚绑定绕开损坏的 PIA/typelib 缓存）

用法：
  python tools/doc2docx.py                 # 转 material/inbox/*.doc  → material/laws/
  python tools/doc2docx.py <文件或目录>...  # 转指定文件/目录（输出到同目录旁的 .docx）

背景：本项目多台机器上 Word 的 Interop 类型库注册损坏，直接 `New-Object -ComObject Word.Application`
会在设置属性时报 TYPE_E_CANTLOADLIBRARY；改用 win32com 的 dynamic dispatch（不生成 makepy 缓存）即可。
"""
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import win32com.client.dynamic as dyn

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "material" / "inbox"
DEFAULT_OUT = ROOT / "material" / "laws"


def targets(args):
    if not args:
        return [(p, DEFAULT_OUT / (p.stem + ".docx")) for p in sorted(DEFAULT_SRC.glob("*.doc"))]
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out += [(q, p / (q.stem + ".docx")) for q in sorted(p.glob("*.doc"))]
        elif p.suffix == ".doc":
            out.append((p, p.with_suffix(".docx")))
        else:
            print("跳过（非 .doc）：", p)
    return out


def main():
    jobs = targets(sys.argv[1:])
    if not jobs:
        print("没有要转换的 .doc")
        return
    for _, dst in jobs:
        dst.parent.mkdir(parents=True, exist_ok=True)
    app = dyn.Dispatch("Word.Application")
    try:
        app.Visible = False
    except Exception as e:
        print("set Visible failed:", e)
    try:
        app.DisplayAlerts = 0
    except Exception as e:
        print("set DisplayAlerts failed:", e)
    for src, dst in jobs:
        print(f"convert: {src.name}", flush=True)
        doc = app.Documents.Open(str(src), False, True)
        doc.SaveAs2(str(dst), 16)   # 16 = wdFormatXMLDocument
        doc.Close(0)
        print(f"  -> {dst}", flush=True)
    app.Quit()
    print("done")


if __name__ == "__main__":
    main()
