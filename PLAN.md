# 法学学习辅助 Agent — 项目计划

## 目标
搭建一个「法学学习辅助 agent」，帮助用户系统性地学习法律知识。
参考思路：https://github.com/amosblomqvist/learn

## 环境状态
- 系统缺少 bash，已启用 Pi 内置 `powershell` 工具作为命令执行后端。
- 参考项目已通过本地代理（127.0.0.1:7897，Clash Verge）经 GitHub API 下载到 `reference-learn/` 并完成研读。
- 技术选型结论：pi 项目配置（`.pi/`）+ TS 扩展（jiti 直载）+ 本地 Markdown 知识库 + DeepSeek。
- **项目根目录已迁移至 `D:\law-learning-agent`**（`.pi` 配置随项目移动，无绝对路径依赖）。
  之后启动学习会话时需在 D:\law-learning-agent 目录下运行 `pi`，否则项目配置不加载。
- 试点 PDF 位于 `D:\法学\民商法\《民法总论》-杨代雄\`，提取脚本直读，无需复制。

## 阶段计划（逐步进行，每步确认后再下一步）
1. 【环境】✅ powershell 可用；git/python3.14/node22/uv 均可用。
2. 【调研】✅ 参考项目研读完成：教学 skill + quiz/ask_user_question/md-log 扩展 + 子代理体系；
   pi 0.87.1 原生支持 mermaid 渲染与 subagent 示例，无需重型外部依赖。
3. 【设计】✅ 已完成：
   - 教学核心：`teach-law` skill（两原则 + 探测→规划→教学 循环 + 法学严谨性规则）
   - 交互：`quiz`（可判分）、`ask_user_question`（开放提问）、`md-log`（Obsidian 镜像）
   - 子代理：`researcher`（调研）、`law-verifier`（法条核验）
   - 可视化：`visualize` skill（mermaid 原生渲染）
   - 知识库：`kb/`（法条库 + 教材分章库）
4. 【选型】✅ 见上。
5. 【实现】进行中：
   - ✅ `.pi/` 配置：skills ×3（`teach-law` 教学：节点二分/苏格拉底纪律/习题册出题纪律/画像机制/核实日志；`practice-law` 练习：drill 拷问 + case 批改 + review 复习三模式；`visualize` 图表）、extensions ×4（quiz/ask/md-log/subagent）、agents ×2
   - ✅ 试点教材导入：《民法总论》教材 15 章 + 习题集 17 单元（题目/答案分离）
   - ✅ 刘家安民法基础课笔记 57 讲提取入库（第 1–56 讲 + 第 59 讲，第 57、58 讲无笔记；含讲次↔章节映射）
   - ✅ 学习者画像（profile.md）、核实日志、错题档案/复习队列（课程进度.md）
   - ✅ 可视化：md-log → Obsidian（项目根即 vault）；`进程树.md` 首页看板；notes 按书/章分目录
   - ✅ 多教材扩展口子：`kb/教材库.md` + profile 当前教材字段 + skill 措辞泛化
   - ✅ 会话提醒菜单（APPEND_SYSTEM：每 session 首条回复报进度 + 入口菜单）；桌面「法学学习.bat」启动器
   - ⬜ 试点教学：新 session 验证全链路（画像→teach→习题册 quiz→md-log→进程树更新）
6. 【打磨】待定：更多法条入库、真实数据测试、文档。（第 24 讲 OCR ✅ 已完成：PaddleOCR-VL）

## 试点方案（《民法总论》）
- 输入：`D:\法学\民商法\《民法总论》-杨代雄\` 下两份 PDF（教材 + 习题集，均带文字层）。
- 管线：`python tools/extract_pdf.py detect`（看结构）→ `extract`（按章切分 markdown）；
  抽完再跑 `python tools/normalize_exercises.py report|apply` 规范化习题 md（去页眉页脚/水印杂字，答案转成「题号 ↦ 答案」清单，并校验题号↔答案条数、选项 A–D 完整性）。
- 产出：`kb/民法总论/教材/*.md`（15 章）、`kb/民法总论/习题/*.md`（17 单元，题目/答案分离）、
  `kb/民法总论/README.md`（章↔页码索引）、`kb/民法总论/课程进度.md`（进度追踪）。
- 教学：按章推进——每章：探测（quiz 摸底）→ 规划（依赖图）→ 教学（逐节点，习题册题目作 quiz 素材）。
- 启动方式：`cd D:\law-learning-agent` 后运行 `pi`（项目 .pi 配置才加载）。

## 备注
- 法学场景关键点：法条引用准确、层级结构（法律/法规/司法解释）、
  判例与法条关联、概念辨析（如「违法」vs「犯罪」）、时效与效力位阶。
