# -*- coding: utf-8 -*-
"""质检：新旧提取件对比 + 残留噪声/异常检查"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "kb" / "参考讲义" / "刘家安民法基础课"
OLD = NEW / "_原始提取"
TYPICAL = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff65\u2014\u2018-\u201d\u2026A-Za-z0-9\s\[\]#>*`\-—「」]")
NOISE = re.compile(r"QQ\s*群|微信|公众号|如有侵权|独家微信|页共|果果考资|一研为定|二维码")

print(f"{'文件':<16}{'旧字符':>8}{'新字符':>8}{'留存':>7}{'注释':>5}{'标记':>5}  异常")
tot_old = tot_new = 0
for new in sorted(NEW.glob("[0-9][0-9]-*.md")):
    old = OLD / new.name
    if not old.exists():
        print(f"{new.name:<16} 缺少旧文件")
        continue
    ot = old.read_text(encoding="utf-8")
    nt = new.read_text(encoding="utf-8")
    tot_old += len(ot)
    tot_new += len(nt)
    notes = len(re.findall(r"(?m)^\[\^\d+\]:", nt))
    marks = len(re.findall(r"\[\^\d+\]", nt)) - notes
    issues = []
    if "⟦" in nt:
        issues.append("未还原标记")
    bad = [l for l in nt.splitlines() if l and len(TYPICAL.findall(l)) / len(l) < 0.75]
    if bad:
        issues.append(f"非典型字符行{len(bad)}")
    if NOISE.search(nt):
        issues.append("残留水印")
    long_paras = [l for l in nt.splitlines() if len(l) > 1200]
    if long_paras:
        issues.append(f"超长段{len(long_paras)}")
    short_paras = [l for l in nt.splitlines() if 0 < len(l) <= 3 and not l.startswith(("#", ">", "[", "|"))]
    if len(short_paras) > 12:
        issues.append(f"碎段{len(short_paras)}")
    print(f"{new.name:<16}{len(ot):>8}{len(nt):>8}{len(nt)/len(ot):>6.0%}{notes:>5}{marks:>5}  {'; '.join(issues)}")
print(f"\n合计 旧={tot_old} 新={tot_new} 留存={tot_new/tot_old:.0%}")
