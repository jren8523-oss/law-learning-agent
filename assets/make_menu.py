# -*- coding: utf-8 -*-
"""生成 README 展示图：pi 菜单（读哪本 / 做哪种题）。"""
from PIL import Image, ImageDraw, ImageFont

BG = (30, 30, 46, 255)        # #1e1e2e
PANEL = (24, 24, 37, 255)     # #181825
TITLE = (203, 166, 247, 255)  # #cba6f7 mauve
ITEM_SEL = (180, 190, 254, 255)  # #b4befe
ITEM = (205, 214, 244, 255)   # #cdd6f4
FOOTER = (108, 112, 134, 255) # #6c7086
CURSOR = (203, 166, 247, 255)

def font(size, bold=False):
    path = r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"
    return ImageFont.truetype(path, size)

W, H = 1400, 600
img = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(img)

def draw_menu(x0, y0, w, h, title, items, footer, sel=0):
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=12, fill=PANEL,
                        outline=(49, 50, 68, 255), width=2)
    tx, ty = x0 + 36, y0 + 34
    d.text((tx, ty), title, font=font(26, True), fill=TITLE)
    ty += 64
    # 光标列宽
    curw = d.textlength("→ ", font=font(22))
    for i, item in enumerate(items):
        if i == sel:
            d.text((tx, ty), "→", font=font(22, True), fill=CURSOR)
            d.text((tx + curw, ty), item, font=font(22, True), fill=ITEM_SEL)
        else:
            d.text((tx + curw, ty), item, font=font(22), fill=ITEM)
        ty += 42
    # 底部提示
    fy = y0 + h - 52
    d.text((tx + curw, fy), footer, font=font(18), fill=FOOTER)

# 左：阅读菜单
draw_menu(
    60, 50, 740, 470,
    "读哪本 / 上哪门课？（民法 · 阅读）",
    ["← 回退", "杨代雄《民法总论》", "解亘《板书体债法总论》", "韩世远《合同法总论》"],
    "↑↓ navigate   enter select   escape/ctrl+c cancel",
    sel=0,
)

# 右：做题菜单
draw_menu(
    840, 50, 500, 470,
    "做哪种题？",
    ["← 回退", "选择题", "案例题"],
    "↑↓ navigate   enter select   escape/ctrl+c cancel",
    sel=0,
)

out = r"D:\law-learning-agent\assets\menu.png"
img.convert("RGB").save(out, "PNG")
print("saved", out, img.size)
