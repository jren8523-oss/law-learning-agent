# -*- coding: utf-8 -*-
"""生成 README 示例图：左侧 pi 项目介绍，右侧模糊 PPT。"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1440, 900
BG = (30, 30, 46, 255)          # #1e1e2e
LEFT_BG = (30, 30, 46, 255)
RIGHT_BG = (24, 24, 37, 255)    # #181825
CODE_BG = (24, 24, 37, 255)     # #181825
TITLE = (245, 194, 231, 255)    # #f5c2e7
H2 = (137, 180, 250, 255)       # #89b4fa
BODY = (166, 173, 200, 255)     # #a6adc8
LIST = (186, 194, 222, 255)     # #bac2de
CODE = (166, 227, 161, 255)     # #a6e3a1
MUTED = (88, 91, 112, 255)      # #585b70

def font(size, bold=False):
    path = r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"
    return ImageFont.truetype(path, size)

def mono(size):
    return ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", size)

img = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(img)

# 分隔线
d.rectangle([W//2, 0, W//2+1, H], fill=(40, 40, 56, 255))

# ---------- 左侧：README 介绍 ----------
x, y = 48, 40
d.text((x, y), "学习 Agent 启动器", font=font(30, True), fill=TITLE)
y += 52
d.text((x, y), "我为自己构建的个人学习系统，按原样分享。它被构建成一个 pi 配置：", font=font(15), fill=BODY)
y += 30
d.text((x, y), "教学哲学被编码进 skills，外加几个小扩展、源卡和子代理定义。", font=font(15), fill=BODY)

y += 52
d.text((x, y), "里面有什么", font=font(20, True), fill=H2)
y += 34
items = [
    ("skills/teach-law/", "带读教材的教学流程与纪律"),
    ("skills/practice-law/", "选择题 / 案例题判分 + 错题复习"),
    ("skills/visualize/", "法律关系图示"),
    ("extensions/opening-greeting/", "启动菜单：学科 → 模式 → 源 → 课节"),
    ("extensions/quiz/", "判分题（✓/✗、正确答案、解释）"),
    ("extensions/md-log/", "会话自动镜像到笔记文件"),
    ("extensions/ask-user-question/", "开放提问"),
    ("sources/", "一源一卡：每本书 / 每门课一张卡"),
    ("agents/", "law-verifier、researcher、notes-editor"),
]
for code, desc in items:
    d.text((x, y), "— ", font=font(13), fill=MUTED)
    w1 = d.textlength("— ", font=font(13))
    d.text((x + w1, y), code, font=mono(12), fill=(249, 226, 175, 255))
    w2 = d.textlength(code, font=mono(12))
    d.text((x + w1 + w2 + 10, y), desc, font=font(13), fill=LIST)
    y += 26

y += 26
d.text((x, y), "安装", font=font(20, True), fill=H2)
y += 34
code_lines = [
    "git clone https://github.com/jren8523-oss/law-learning-agent.git my-course",
    "cd my-course",
    "pi",
]
d.rounded_rectangle([x, y, x + 600, y + 72], radius=8, fill=CODE_BG)
ty = y + 12
for line in code_lines:
    d.text((x + 16, ty), line, font=mono(12), fill=CODE)
    ty += 20
y += 92

d.text((x, y), "移植到其他学科", font=font(20, True), fill=H2)
y += 34
d.text((x, y), "这是为法学建的。想移植到经管、计算机、哲学……直接问 AI：", font=font(14), fill=BODY)
y += 28
d.text((x + 24, y), "「我要学【你的学科】，帮我看看要改哪些文件。」", font=font(14), fill=(203, 166, 247, 255))

# ---------- 右侧：模糊 PPT ----------
# 先画一张清晰的 PPT 到单独图层，再模糊后贴回
ppt_w, ppt_h = 560, 420
ppt = Image.new("RGBA", (ppt_w, ppt_h), (42, 42, 58, 255))
pd = ImageDraw.Draw(ppt)
# 标题条
pd.rectangle([0, 0, ppt_w, 56], fill=(58, 58, 80, 255))
pd.text((24, 14), "第三章 · 债的效力", font=font(22, True), fill=TITLE)
# 正文
ty = 76
body = [
    ("一、债权的四项权能", True),
    ("  1. 请求力 —— 债权人得请求债务人给付", False),
    ("  2. 给付保持力 —— 受领后得永久保持", False),
    ("  3. 诉求力 —— 诉请法院强制履行", False),
    ("  4. 执行力 —— 依执行名义申请强制执行", False),
    ("", False),
    ("二、不完全债务", True),
    ("  • 自然债务：有给付保持力，无请求力与诉求力", False),
    ("  • 罹于时效的债务", False),
    ("  • 赌博债务", False),
]
for text, bold in body:
    if text:
        pd.text((24, ty), text, font=font(17, bold), fill=LIST if not bold else (203, 166, 247, 255))
    ty += 30

# 模糊 + 半透明
ppt = ppt.filter(ImageFilter.GaussianBlur(8))
mask = Image.new("L", (ppt_w, ppt_h), 120)
ppt.putalpha(mask)
img.alpha_composite(ppt, (W//2 + (560 - ppt_w)//2, (H - ppt_h)//2 - 20))

# 右下角页标签
label = "第 3 周 · p12"
lw = d.textlength(label, font=font(13))
d.text((W - lw - 24, H - 40), label, font=font(13), fill=MUTED)

img = img.convert("RGB")
out = r"D:\law-learning-agent\assets\demo.png"
img.save(out, "PNG")
print("saved", out, img.size)
