# -*- coding: utf-8 -*-
"""验收课件转换稿：页标记是否连续、有没有空页。

用法:
    python checkmd.py <转换稿.md> [更多.md ...]
    python checkmd.py kb/课件文本          # 整个目录
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^## p(\d+)$", text, flags=re.M)
    nums = [int(parts[i]) for i in range(1, len(parts), 2)]
    bodies = [parts[i + 1].strip() for i in range(1, len(parts), 2)]
    if not nums:
        print(f"✗ {path.name}: 一个页标记都没有 —— 转换失败（或它是扫描件）")
        return False
    continuous = nums == list(range(1, len(nums) + 1))
    blank = sum(1 for b in bodies if not b)
    ok = continuous and blank < len(nums) * 0.5
    print(f"{'✓' if ok else '✗'} {path.name}: {len(nums)} 页, 范围 p{nums[0]}-p{nums[-1]}, "
          f"页号连续={continuous}, 空白页={blank}")
    if not continuous:
        dup = sorted({n for n in nums if nums.count(n) > 1})
        missing = sorted(set(range(1, len(nums) + 1)) - set(nums))
        print(f"   重复：{dup[:20]} 缺失：{missing[:20]}")
    if blank >= len(nums) * 0.5:
        print(f"   ⚠ 过半页面没文字 —— 多半是扫描件/图片型课件，先 OCR 再讲课")
    return ok


def main() -> None:
    args = [Path(a) for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    files: list[Path] = []
    for a in args:
        files += sorted(a.glob("*.md")) if a.is_dir() else [a]
    bad = [f for f in files if not check(f)]
    print(f"\n{len(files)} 份，{len(bad)} 份有问题。")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
