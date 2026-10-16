# -*- coding: utf-8 -*-
"""用用户真实截图生成 README 展示图；图4 右半 PPT 打马赛克。"""
import os
import shutil

from PIL import Image

SESS = r"C:\Users\lenovo\.kimi-code\sessions\wd_law-learning-agent_fd7a2cb7ef95\session_373208cc-0d58-47c4-a8bf-0ebf8bd864e0"
OUT = r"D:\law-learning-agent\assets"
os.makedirs(OUT, exist_ok=True)

# 菜单：直接用用户截图（读哪本 / 做哪种题）
shutil.copy(SESS + r"\media\f_2bae8b91-9126-473c-8f8d-86a35b2bf582.png", OUT + r"\menu-read.png")
shutil.copy(SESS + r"\media\f_42700765-2d28-4d56-a288-9df24932468e.png", OUT + r"\menu-drill.png")

# 主页：pi 启动菜单（今天做什么？汇总/上课/阅读/做题/设置）
shutil.copy(SESS + r"\media-originals\3c8ba41a580c98c1f11d33d3afae68ca.png", OUT + r"\menu-main.png")

# 上课场景：保留左侧 agent 讲解，右侧 PPT 打马赛克（避免版权）
src = SESS + r"\media-originals\4e0f0c08ebf10f2b3b2c89c28a0a159f.png"
im = Image.open(src).convert("RGB")
w, h = im.size
xs = int(w * 0.51)  # 右半（PPT 窗口）起点
right = im.crop((xs, 0, w, h))
small = right.resize((max(1, right.width // 26), max(1, right.height // 26)), Image.BOX)
im.paste(small.resize(right.size, Image.NEAREST), (xs, 0))
im.save(OUT + r"\teach.png")
print("ok", im.size, "split at x =", xs)
