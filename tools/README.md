# tools/ — 素材管线与脚本

> 只在**用到时**读本文件，不要凭记忆跑脚本。项目日常教学不需要这里的东西。

## 一、OCR 云管线（纯扫描 PDF，一律走这条；不要用本地 RapidOCR 的 `ocr_book.py`）

1. `python tools/chunk_pdf.py` 把 PDF 切成 10 页/块；
2. 设 `PADDLEOCR_ACCESS_TOKEN`（token 在 `~/.pi/agent/mcp.json` 的 `paddleocr-vl` 段 env 里）；
3. 用 `.paddleocr-mcp-venv` 的 python 跑 `tools/ocr_paddlecloud.py`（断点续跑，块结果入 JSON 缓存，输出 txt 带页标记）。

## 二、PDF → markdown 提取（有文字层的书）

| 脚本 | 适用 |
|---|---|
| `extract_pdf.py` | 杨代雄《民法总论》式：`detect` 看结构 → `extract [--only 教材|习题]` 按章／按单元切分 |
| `extract_zhaifa.py` | 债法类教材（TOC 书签驱动，按章切分） |
| `extract_book.py` | 通用（TOC 书签驱动） |
| `extract_wzj_book.py` | 王泽鉴单本（书签驱动 ＋ 节标题注入 ＋ 脚注抽出 ＋ 原书页码还原） |
| `extract_wq.py` / `clean_zhaifang.py` | 页眉 heading-scan／PPT 导出 PDF 的逐页清洗 |
| `extract_laws.py` / `extract_laws_extra.py` | 法条、司法解释（docx → markdown，一字不改） |
| `import_ocr_books.py` / `import_判例百选.py` | OCR 结果切章入库 |
| `normalize_exercises.py` | 习题 md 规范化与对账（`report` / `apply` / `check-md`） |
| `doc2docx.py` | 旧 `.doc` → `.docx` |

## 三、检查脚本

- `tools/check_state.py`：收工前状态对账（复习队列／错题档案计数是否与看板一致、最近触及日期、notes 章目录命名）。
- `tools/_task_notes_editor.md`：`notes-editor` 子代理的任务书模板。

## 四、约定

- 提取脚本**不改正文**：只去页眉/页码/水印杂字，正文一字不动。
- 已入库的书 PDF → `material/pdf/`；**真题原件** → `material/pdf/真题/`；用过的法条源 → `material/laws/`；**课件**（含上课线课件队列）→ `material/ppt/<课程>/`；**课堂录音与转写** → `material/录音/<课程>/`；`material/inbox/` 只留未用上的。
- 新书入库判断（类型、角色、登记）见 `kb/教材库.md`。
