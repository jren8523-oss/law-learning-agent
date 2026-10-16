# 学习 Agent 启动器

一个基于 pi 的 AI 辅助学习系统。法学是第一个用例，可以移植到任何学科。

## 这是什么

我自己用的学习系统，按原样分享。教学哲学被编码进 skills 和扩展，外加源卡（source cards）管理多本书、多门课并行。

## 里面有什么

- `skills/teach-law/` —— 带读教材的教学流程与纪律
- `skills/practice-law/` —— 选择题 / 案例题判分 + 错题复习
- `skills/visualize/` —— 法律关系图示
- `extensions/opening-greeting/` —— 启动菜单：学科 → 模式 → 源 → 课节
- `extensions/quiz/` —— 判分题（✓/✗、正确答案、解释）
- `extensions/md-log/` —— 会话自动镜像到笔记文件
- `extensions/ask-user-question/` —— 开放提问
- `sources/` —— 一源一卡：每本书 / 每门课一张卡（frontmatter + 教法）
- `agents/` —— `law-verifier`（法条核验）、`researcher`（调研）、`notes-editor`（讲义校对）

## 安装

这个仓库**本身就是一个项目目录**。克隆后，用 pi 打开即可：

```
git clone https://github.com/jren8523-oss/law-learning-agent.git my-course
cd my-course
pi
```

## 移植到其他学科

这是为法学建的。想移植到经管、计算机、哲学……直接问 AI：

> 「我要学【你的学科】，帮我看看要改哪些文件。」

AI 会读你的仓库，逐个文件告诉你改什么。核心要改的只有几处：`skills/` 里的学科纪律、`sources/` 里的源卡、`APPEND_SYSTEM.md` 里的规则。`extensions/` 是学科无关的，不用动。