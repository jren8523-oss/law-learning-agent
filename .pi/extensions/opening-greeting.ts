/**
 * opening-greeting — 会话开始由**代码**完成「选源」，并把该源的卡与只读清单注入会话。
 *
 * 一源一卡：源 ＝ 一本书或一门课，一张卡 ＝ `.pi/sources/<id>.md`
 * （frontmatter 带菜单字段，正文＝该源的教法、材料范围与边界）。
 * 加一个源 ＝ 加一个卡文件，本文件不用改。
 *
 * 菜单（能省则省，剩一个就不问）：
 *   学科 → 模式（**上课 / 阅读 / 做题 / 汇总 / 设置**）→ 做题再分题型（选择题 / 案例题）
 *   → 源（按模式过滤：做题目录＝有题库 `banks` 的卡，直接列题库）／上课类再选课节（推荐＝清单第一个 🔄，否则第一个 ⬜）／阅读类再选章、选节（卡里有 `chapters:` 章清单时；读不到该文件就跳过）。
 * 模式来自卡片的 `modes` 字段、题库来自 `banks` 字段，所以往卡里加就能长出新的菜单项（不必改本文件）。
 * 「汇总」＝总账模式（卡里写 `modes: 汇总`，见 `.pi/sources/weekly.md`）：平时按 `MODE_ORDER` 排在模式列表**最后**；
 * 周五／周六／周日（本周还没记）或周一–周四而**上周也没记**时，代码（`shouldNudgeWeekly`）把它挪到「今天做什么？」的
 * **第一位**，标签写成「汇总（推荐 · 本周汇总还没记：<ISO 周> <范围>）」；周号与范围由 `isoWeek` 算（周一起算）。
 * 「设置」＝项目设置模式（卡里写 `modes: 设置`，见 `.pi/sources/settings.md`）：按 `MODE_ORDER` 排在汇总**之后**，**永不推荐**（不做周汇总那种挪位）；
 * 它的导航消息也跟教学会话相反——收尾不写「本会话只准读／不许读」，而写成「**本会话要读**」＋「**本会话例外**」：
 * `.pi/`（源卡／skills／子代理／extensions／项目约定）、`进程树.md`、`学习路线.md`、`agent评估报告.md` 正是要读的。
 *
 * 流程：session_start（startup/new/resume）→
 *   · 本会话已记录过源 → 直接续注入那张卡（不弹菜单，resume 不打扰）；
 *   · 否则走上面的菜单；
 *   · 生成的「[学习导航]」用户消息里带：源的卡正文（内联，agent 不必再读、不必判断）
 *     ＋ 模式（含题型）＋ 本次课节／题库 ＋ 本会话只准读的路径清单 ＋ 路线定位一句
 *     （从 `学习路线.md` §六 由**代码**摘出）。
 *   · 阅读类选完节后，还多一段「**本节材料**」：教材文件与**本节页段**（同文件下一节的起始页 −1；
 *     本章末节取该书 README 章表的末页）／深度层讲义（卡里 `depth:` 指的章↔讲次映射文件，如
 *     `kb/参考讲义/刘家安民法基础课/README.md`）／本节习题（答案只给路径，判分时才读）／本节笔记目录
 *     与最近两份。取不到的项直接不写（不猜）。这样 agent 不必自己 `ls`／`find`／`grep` 找路，
 *     也不必为「我该读哪份、读到哪」花一轮思考。
 *   pi.appendEntry 记住本会话的选择，供 resume 与 `/source` 复用。
 *   `/weekly`（以及 `/汇总`，若 pi 接受非 ASCII 命令名）＝直接开一个汇总会话，不必从菜单点。
 *
 * 汇总会话（`picked.weekly`）的导航消息**与教学会话相反**：教学会话只写本源进度文件、不碰全局，
 * 所以「这一周做了什么」得靠汇总会话一次补齐——`学习路线.md`／`进程树.md` 在这里正是**要读**的：
 * 「**本会话只准读**」改成「**本会话要读**」（内容＝卡的 `read:` ＋ 各源卡 `progress:`／`ledger:`，见 `weeklyPaths`），
 * 末尾那句「**不许读**」换成「**本会话例外**」；本次一行写「本周汇总 <ISO 周>（<范围>）→ 写 `进程树.md` 的『周记』节」。
 * 该卡没有 `route:`，所以汇总会话不出「**路线**」行（现有代码本来就跳过）。
 *
 * 为什么把卡与清单塞进消息：选什么、读什么全部由代码算好，agent 不必自己探索，
 * 也不必读 `学习路线.md` / `进程树.md` 这些全局文件（省 token；只有汇总与设置这两个会话是例外）。
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { exec } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SOURCES_DIR = ".pi/sources";
const ROUTE_FILE = "学习路线.md";
const ENTRY_TYPE = "law-source";
const GREET_REASONS = new Set(["startup", "new", "resume"]);
/** 总账文件（就是 Obsidian 首页，相对工作目录）：汇总会话写它的「周记」节。 */
const WEEKLY_FILE = "进程树.md";
/** 汇总模式的模式名；声明了它的源卡＝总账卡（`modes: 汇总`）。 */
const WEEKLY_MODE = "汇总";
/** 设置模式的模式名；声明了它的源卡＝项目设置卡（`modes: 设置`）——导航消息也反过来：项目自身的文件正是要读的。 */
const SETTINGS_MODE = "设置";
/** 模式级的显示顺序；卡片里出现的其他模式排在后面。 */
const MODE_ORDER = ["上课", "阅读", "做题", "刷题", "沟通", "自检", WEEKLY_MODE, SETTINGS_MODE];
/** 模式下的题型级（只有「做题」有）；题型 → 走 practice-law 的哪个模式。 */
const SUBTYPES: Record<string, string[]> = { 做题: ["选择题", "案例题"] };
const SUBTYPE_ROUTE: Record<string, string> = {
	选择题: "practice-law 的 **drill**（`quiz` 即时判分；辨析/简答走自由作答后对照答案）",
	案例题: "practice-law 的 **case**（不代写：他先写，你只批改；四维批改＝争点/规则/涵摄/结论）",
};

interface Bank {
	path: string;
	label: string;
}

interface SourceCard {
	id: string;
	title: string;
	subject: string;
	modes: string[];
	banks: Bank[];
	dir?: string;
	progress?: string;
	notes?: string;
	ledger?: string;
	/** 阅读类：章清单（部｜章｜节｜教材文件｜页｜状态）的路径，相对工作目录；没有＝这一源不问选章 */
	chapters?: string;
	/** 阅读类：深度层（穿插讲义）的章↔讲次映射文件，相对工作目录（`- **<章名>** → 第N讲, …`） */
	depth?: string;
	lectures?: string;
	lectureInclude?: string;
	/** 逐页文本缓存的相对路径（相对卡目录 `dir`）；省略则按 `周课/<课件编号>.md` 推。 */
	cache?: string;
	route?: string;
	order: number;
	read: string[];
	/** 相对工作目录的卡文件路径 */
	file: string;
	/** 卡正文（注入给 agent 的那段） */
	body: string;
}

type LessonStatus = "done" | "doing" | "todo";

interface Lesson {
	/** 相对工作目录的课件路径 */
	file: string;
	label: string;
	status: LessonStatus;
}

/** 章清单的一行（节级）：部 ／ 章 ／ 节 ＋ 教材文件、页码、状态。 */
interface ChapterRow {
	/** 部名，如「第1部 债的基本概念」 */
	part: string;
	/** 章名，如「第2章 债权的效力总论」 */
	chapter: string;
	/** 节名，如「第1节 债权通常具有的权能」；不分节的章写作「（无节，整章一读）」 */
	section: string;
	/** 教材文件名（相对 `<卡 dir>/教材/`） */
	file: string;
	/** 原书起始页码 */
	page?: string;
	status: LessonStatus;
}

interface Picked {
	card: SourceCard;
	mode: string;
	subtype?: string;
	bank?: Bank;
	lesson?: Lesson;
	/** 阅读类：用户在菜单里对读法的选择 */
	reading?: "继续" | "调整";
	/** 阅读类：菜单里展示过的那段读法原文（该书 README 的「阅读线读法」节） */
	readingText?: string;
	/** 阅读类：选中的章（章名；同名章分散在不同部下时带部名） */
	chapter?: string;
	/** 阅读类：选中的那一行（章清单的节级行） */
	section?: ChapterRow;
	/** 汇总类：本次是总账会话（卡声明了 `modes: 汇总` 且模式选的就是它）——导航消息与教学会话相反 */
	weekly?: boolean;
	/** 续上会话（resume 而非新选）：章/节是上次选中的，导航消息里提示以本源进度文件为准 */
	resumed?: boolean;
}

// --- 卡文件解析 ---

/** 极简 frontmatter：只认 `key: value` 与 `key:` ＋ `- item` 两种形态（够用即可，不引 YAML 依赖）。 */
function parseCard(text: string): { meta: Record<string, string | string[]>; body: string } {
	const matched = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
	if (!matched) return { meta: {}, body: text.trim() };

	const meta: Record<string, string | string[]> = {};
	let listKey: string | null = null;
	for (const rawLine of matched[1].split(/\r?\n/)) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;

		const item = /^-\s+(.+)$/.exec(line);
		if (item && listKey) {
			(meta[listKey] as string[]).push(unquote(item[1]));
			continue;
		}

		const pair = /^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/.exec(line);
		if (!pair) continue;
		const value = pair[2].trim();
		if (value === "") {
			meta[pair[1]] = [];
			listKey = pair[1];
		} else {
			meta[pair[1]] = unquote(value);
			listKey = null;
		}
	}
	return { meta, body: text.slice(matched[0].length).trim() };
}

function unquote(value: string): string {
	const text = value.trim();
	const quoted =
		(text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"));
	return quoted ? text.slice(1, -1) : text;
}

function asList(value: string | string[] | undefined): string[] {
	if (value === undefined) return [];
	if (Array.isArray(value)) return value;
	return value
		.split(",")
		.map((item) => item.trim())
		.filter(Boolean);
}

function asText(value: string | string[] | undefined): string | undefined {
	if (value === undefined) return undefined;
	return Array.isArray(value) ? value[0] : value;
}

/** `banks` 每项写成 `路径|显示名`（显示名可省，省了取路径末段）。 */
function asBanks(value: string | string[] | undefined): Bank[] {
	return asList(value)
		.map((raw) => {
			const cut = raw.indexOf("|");
			const rawPath = (cut < 0 ? raw : raw.slice(0, cut)).trim();
			const label = cut < 0 ? "" : raw.slice(cut + 1).trim();
			const fallback = rawPath.replace(/\/+$/, "").split("/").pop() ?? rawPath;
			return { path: rawPath, label: label || fallback };
		})
		.filter((bank) => bank.path.length > 0);
}

/** 扫 `.pi/sources/` 读全部源卡；没正文的 md 不算源卡（跳过）。 */
function loadSources(cwd: string): SourceCard[] {
	const dir = path.join(cwd, SOURCES_DIR);
	let names: string[];
	try {
		names = fs.readdirSync(dir).filter((name) => name.endsWith(".md"));
	} catch {
		return [];
	}

	const cards: SourceCard[] = [];
	for (const name of names) {
		let text: string;
		try {
			text = fs.readFileSync(path.join(dir, name), "utf8");
		} catch {
			continue;
		}
		const { meta, body } = parseCard(text);
		if (!body) continue;

		const id = asText(meta.id) ?? path.basename(name, ".md");
		cards.push({
			id,
			title: asText(meta.title) ?? id,
			subject: asText(meta.subject) ?? "未分类",
			modes: asList(meta.modes),
			banks: asBanks(meta.banks),
			dir: asText(meta.dir),
			progress: asText(meta.progress),
			notes: asText(meta.notes),
			ledger: asText(meta.ledger),
			chapters: asText(meta.chapters),
			depth: asText(meta.depth),
			lectures: asText(meta.lectures),
			lectureInclude: asText(meta.lectureInclude),
			cache: asText(meta.cache),
			route: asText(meta.route),
			order: Number(asText(meta.order)) || 100,
			read: asList(meta.read),
			file: `${SOURCES_DIR}/${name}`,
			body,
		});
	}
	return cards.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
}

// --- 「今天」与 ISO 周（汇总模式：周五推荐、「本周」标签） ---

/** 「今天」：`LAW_TODAY`（YYYY-MM-DD）可覆盖，供验收探针与手动试跑。 */
function today(now?: Date): Date {
	const override = /^(\d{4})-(\d{2})-(\d{2})$/.exec((process.env.LAW_TODAY ?? "").trim());
	if (override) return new Date(Number(override[1]), Number(override[2]) - 1, Number(override[3]));
	return now ?? new Date();
}

/** 周号两位数：`isoLabel(2026, 42)` ＝ `2026-W42`。 */
function isoLabel(year: number, week: number): string {
	return `${year}-W${String(week).padStart(2, "0")}`;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** 本地日历日的 UTC 零点：天数算术不必担心夏令时多／少一小时。 */
function utcMidnight(date: Date): number {
	return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
}

/**
 * ISO 8601 周（周一起算，含 1 月 4 日的那周为第 1 周）：周号归到**该周周四所在的年**。
 * `label` ＝ `2026-W42`；`range` ＝ 周一–周日的 `MM-DD～MM-DD`；`monday` ＝ 该周周一（UTC 零点）。
 */
function isoWeek(date: Date): { year: number; week: number; label: string; range: string; monday: Date } {
	const base = utcMidnight(date);
	const offset = (new Date(base).getUTCDay() + 6) % 7; // 0＝周一
	const thursday = new Date(base + (3 - offset) * DAY_MS);
	const year = thursday.getUTCFullYear();
	const jan4 = Date.UTC(year, 0, 4);
	const firstThursday = jan4 + (3 - ((new Date(jan4).getUTCDay() + 6) % 7)) * DAY_MS;
	const week = 1 + Math.round((thursday.getTime() - firstThursday) / (7 * DAY_MS));
	const monday = new Date(thursday.getTime() - 3 * DAY_MS);
	const sunday = new Date(thursday.getTime() + 3 * DAY_MS);
	const monthDay = (day: Date) =>
		`${String(day.getUTCMonth() + 1).padStart(2, "0")}-${String(day.getUTCDate()).padStart(2, "0")}`;
	return {
		year,
		week,
		label: isoLabel(year, week),
		range: `${monthDay(monday)}～${monthDay(sunday)}`,
		monday,
	};
}

/** 上一周：周 1 的上周＝上一年的最后一周（＝含 12-28 的那周）。 */
function previousWeek(iso: { year: number; week: number }): { year: number; week: number } {
	if (iso.week > 1) return { year: iso.year, week: iso.week - 1 };
	const last = isoWeek(new Date(iso.year - 1, 11, 28));
	return { year: last.year, week: last.week };
}

/**
 * 本周（`label`，如 `2026-W42`）是否已记进总账：认**标题行** `### 2026-W42…`（周记条目的写法）。
 * HTML 注释（`<!-- … -->`，里面放着格式模板）先剥掉——模板里那行 `### 2026-W42（…）` 不算已记；
 * 正文里偶然提到某个周号也不算。读不到 `进程树.md` 就当没记。
 */
function weeklyTagged(cwd: string, label: string): boolean {
	let text: string;
	try {
		text = fs.readFileSync(path.join(cwd, WEEKLY_FILE), "utf8");
	} catch {
		return false;
	}
	const stripped = text.replace(/<!--[\s\S]*?-->/g, "");
	const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	return new RegExp(`^#{2,4}\\s*${escaped}(?![0-9])`, "m").test(stripped);
}

/**
 * 要不要推荐「汇总」：本周已记 → 不推；周五／周六／周日 → 推；周一–周四 → 上周也没记才推（＝上周也漏了，提示补做）。
 */
function shouldNudgeWeekly(cwd: string, date: Date): boolean {
	const current = isoWeek(date);
	if (weeklyTagged(cwd, current.label)) return false;
	const day = date.getDay();
	if (day === 5 || day === 6 || day === 0) return true;
	const last = previousWeek(current);
	return !weeklyTagged(cwd, isoLabel(last.year, last.week));
}

/** 汇总会话要读的全局／各源路径：每张卡的 `progress` 与 `ledger`（有则取），去重、按卡序保序。 */
function weeklyPaths(cards: SourceCard[]): string[] {
	const paths: string[] = [];
	for (const card of cards) {
		for (const entry of [card.progress, card.ledger]) {
			if (entry && !paths.includes(entry)) paths.push(entry);
		}
	}
	return paths;
}

// --- 路线与课节（都由代码读，agent 不读这些全局文件） ---

/** 摘 `学习路线.md` §六 里 `- **<key>**：…` 那一行；没有就返回 undefined。 */
function routeLine(cwd: string, key: string): string | undefined {
	let text: string;
	try {
		text = fs.readFileSync(path.join(cwd, ROUTE_FILE), "utf8");
	} catch {
		return undefined;
	}
	const pattern = new RegExp(
		`^-\\s*\\*\\*${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\*\\*\\s*[:：]\\s*(.+)$`,
		"m",
	);
	const matched = pattern.exec(text);
	return matched ? matched[1].trim() : undefined;
}

/**
 * 状态列（上课状态）写法：`⬜ 未上`／`🔄 进行中`／`✅ 上完`。
 * 只认「上/讲」字系的完成词——这一列里出现过 `✅ 已整理`（转写整理进度，与上课无关），
 * 早先「见 ✅ 就算上完」把第 4–10 周虚报成已上完。认不出的写法一律当未上（宁漏报不虚报）。
 */
function lessonStatus(cell: string): LessonStatus {
	if (/🔄|进行中/.test(cell)) return "doing";
	if (/未(上|讲|开始|完)/.test(cell)) return "todo";
	return /✅\s*(上完|已上|上过|讲完)/.test(cell) ? "done" : "todo";
}

/** 解析课件清单：课件文件名 → { 页数, 该节音频段, 状态 }。取每行最后一个非空单元格作状态。 */
function parseLedger(file: string): Map<string, { pages?: string; audio?: string; status: LessonStatus }> {
	const map = new Map<string, { pages?: string; audio?: string; status: LessonStatus }>();
	let text: string;
	try {
		text = fs.readFileSync(file, "utf8");
	} catch {
		return map;
	}
	for (const line of text.split(/\r?\n/)) {
		if (!line.startsWith("|")) continue;
		const cells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
		const nameIndex = cells.findIndex((cell) => cell.startsWith("`") && cell.endsWith("`"));
		if (nameIndex < 0) continue;
		const name = cells[nameIndex].slice(1, -1);
		const last = cells[cells.length - 1] ?? "";
		const status: LessonStatus = lessonStatus(last);
		const pages = /^\d+$/.test(cells[nameIndex + 1] ?? "") ? cells[nameIndex + 1] : undefined;
		// 清单列序：周｜次｜课件文件｜页数｜对应音频段｜转写｜状态 ——「对应音频段」紧跟在页数之后
		map.set(name, { pages, audio: cells[nameIndex + 2] ?? "", status });
	}
	return map;
}

/** 一节课自己的只读材料：逐页缓存、该节转写稿、纠错表。**别的节次的料不进这里**（省 token）。 */
function lessonExtras(card: SourceCard, cwd: string, name: string, audio?: string): string[] {
	if (!card.dir) return [];
	const exists = (relative: string) => fs.existsSync(path.join(cwd, relative));
	const extras: string[] = [];

	const stem = /^(\d\d(?:\.\d)?)\./.exec(name)?.[1] ?? path.basename(name, ".pdf");
	const cache = card.cache ? `${card.dir}/${card.cache}` : `${card.dir}/周课/${stem}.md`;
	if (exists(cache)) extras.push(cache);

	for (const token of (audio ?? "").split(/[\s、,，/|]+/)) {
		if (!/^第\S+周/.test(token)) continue;
		// 整理稿优先：`整理/` 是去过口语的课堂稿，`原始/` 是逐字转写（存档，仅回溯用）
		const transcript = ["整理", "原始"]
			.map((kind) => `${card.dir}/录音讲稿/${kind}/${token}.md`)
			.find(exists);
		if (transcript) extras.push(transcript);
	}

	const glossary = `${card.dir}/录音讲稿/_纠错表.md`;
	if (exists(glossary)) extras.push(glossary);
	return extras;
}

/** 课节标签：`第 N 节 · 第1周周二上午 · 66 页`（不含文件名）。 */
function lessonLabel(name: string, index: number, pages?: string): string {
	const parts: string[] = [];
	const week = /^(\d\d)(\.\d)?\./.exec(name);
	if (week) {
		const when = /（([^）]+)）/.exec(name)?.[1];
		parts.push(`第${Number(week[1])}周${when ?? ""}`);
	}
	if (pages) parts.push(`${pages} 页`);
	const label = `第 ${index + 1} 节`;
	return parts.length > 0 ? `${label} · ${parts.join(" · ")}` : label;
}

function listLessons(card: SourceCard, cwd: string): Lesson[] {
	if (!card.lectures) return [];
	const include = card.lectureInclude ? new RegExp(card.lectureInclude) : /\.pdf$/i;
	let names: string[];
	try {
		names = fs.readdirSync(path.join(cwd, card.lectures)).filter((name) => include.test(name));
	} catch {
		return [];
	}
	names.sort();
	const ledger = card.ledger ? parseLedger(path.join(cwd, card.ledger)) : new Map();
	return names.map((name, index) => {
		const meta = ledger.get(name);
		return {
			file: `${card.lectures}/${name}`,
			label: lessonLabel(name, index, meta?.pages),
			status: meta?.status ?? "todo",
			extra: lessonExtras(card, cwd, name, meta?.audio),
		};
	});
}

/** 推荐课节：优先续上未上完的（🔄），否则第一个没上过的（⬜）；全上完则 undefined。 */
function recommendIndex(lessons: Lesson[]): number {
	const doing = lessons.findIndex((lesson) => lesson.status === "doing");
	if (doing >= 0) return doing;
	return lessons.findIndex((lesson) => lesson.status !== "done");
}

// --- 导航消息 ---

/** 本会话只准读的路径：卡声明的 read ＋ 该源进度文件／清单 ＋ 本次课件与本节材料 ＋ 题库 ＋ 两个全局白名单。 */
function allowedPaths(picked: Picked): string[] {
	const paths = picked.card.read.slice();
	const add = (entry?: string) => {
		if (entry && !paths.includes(entry)) paths.push(entry);
	};
	add(picked.card.progress);
	add(picked.card.ledger);
	add(picked.lesson?.file);
	for (const entry of picked.lesson?.extra ?? []) add(entry);
	add(picked.bank?.path);
	paths.push("profile.md（学习者画像）");
	paths.push("kb/laws/（法条核对：先 grep 定位，禁止整读）");
	return paths;
}

// --- 阅读类：本节的料（教材页段／深度层讲次／习题／笔记，全由代码算好，agent 不必自己找） ---

/** 去空白（含全角），供表里的写法与存法对不上时比对用。 */
function squash(text: string): string {
	return text.replace(/[\s\u3000]+/g, "");
}

/** 两处是不是指同一章：去空白后互含（`第九章 法律行为与意思表示` ⊂ `…的一般原理`）。 */
function looksSame(a: string, b: string): boolean {
	const left = squash(a);
	const right = squash(b);
	if (left.length < 2 || right.length < 2) return false;
	return left === right || left.includes(right) || right.includes(left);
}

/** 本章末页：该书 README 的章↔页码表里对上的那一行（先按教材文件名，再按章名）。 */
function chapterEndPage(card: SourceCard, cwd: string, row: ChapterRow): string | undefined {
	if (!card.dir) return undefined;
	let text: string;
	try {
		text = fs.readFileSync(path.join(cwd, card.dir, "README.md"), "utf8");
	} catch {
		return undefined;
	}
	for (const line of text.split(/\r?\n/)) {
		if (!line.startsWith("|")) continue;
		const cells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
		if (cells.length < 3) continue;
		if (!cells.some((cell) => looksSame(cell, row.file) || looksSame(cell, row.chapter))) continue;
		// 页码列的位置按书不同（杨代雄表 3 列、解亘表多一列「部/编」），所以整行找页码格，别锚列号；
		// 习题表同格的写法是 `126-131，答案见 …`，锚定两端就自然跳过
		const ranges = cells.map((cell) => /^(\d+)\s*[-–—~至]\s*(\d+)$/.exec(cell)).filter((hit) => hit !== null);
		const last = ranges[ranges.length - 1];
		if (last) return last[2];
	}
	return undefined;
}

/**
 * 本节页段 `508-515`：同一教材文件里下一节的起始页 −1（下一节的页不比本节大就用不上，见下）；
 * 本章末节、或章清单没把页码细到节（几节共用一章的起始页）时，取该书 README 章表的末页。
 * 两头都取不到就只给起始页——宁可少给，也不给一个错的区间。
 */
function sectionPages(card: SourceCard, cwd: string, row: ChapterRow, rows: ChapterRow[]): string | undefined {
	if (!row.page) return undefined;
	const siblings = rows.length > 0 ? rows.filter((item) => item.file === row.file) : [row];
	const index = siblings.indexOf(row);
	const next = index >= 0 ? siblings[index + 1] : undefined;
	const bound = next?.page && Number(next.page) > Number(row.page) ? String(Number(next.page) - 1) : undefined;
	const end = bound ?? chapterEndPage(card, cwd, row);
	return end && Number(end) > Number(row.page) ? `${row.page}-${end}` : row.page;
}

/** 卡里 `depth:` 指的映射文件（`- **第十三章 权利救济** → 第7讲, 第55讲 …`）→ 本源深度层的讲义文件路径。 */
function depthFiles(card: SourceCard, cwd: string, chapter: string): string[] {
	if (!card.depth) return [];
	const file = path.join(cwd, card.depth);
	let text: string;
	try {
		text = fs.readFileSync(file, "utf8");
	} catch {
		return [];
	}

	let lectures: string[] = [];
	for (const line of text.split(/\r?\n/)) {
		const matched = /^[-*]\s*\*\*(.+?)\*\*\s*[→:：]\s*(.+)$/.exec(line.trim());
		if (!matched || !looksSame(matched[1], chapter)) continue;
		lectures = matched[2]
			.split(/[,，、|]/)
			.map((item) => item.trim())
			.filter(Boolean);
		break;
	}
	if (lectures.length === 0) return [];

	const dir = path.dirname(file);
	let names: string[];
	try {
		names = fs.readdirSync(dir);
	} catch {
		return [];
	}
	const prefix = path.relative(cwd, dir).split(path.sep).join("/");
	const files: string[] = [];
	for (const label of lectures) {
		const number = Number(/第\s*(\d+)\s*讲/.exec(label)?.[1]);
		if (!Number.isFinite(number)) continue;
		const hit = names.find((name) => Number(/^\d+-第(\d+)讲\.md$/.exec(name)?.[1]) === number);
		if (hit) files.push(`${prefix}/${hit}`);
	}
	return files;
}

/** 期末模拟卷／附加作业这类不与任何章对应的单元（README 习题表标签里认出来）。 */
const EXAM_LIKE = /模拟卷|附加作业|期末|试卷/;

/**
 * 本节的习题：单元↔章的映射以该书 README 的**习题表**为权威——
 *   ① 同号：章清单「教材文件」列的前缀号 ＝ 单元号（杨代雄：单元一↔第一章 … 单元十四↔第十四章）；
 *      但若表里该单元的标签是「模拟卷／附加作业」这类**不与任何章对应**的单元，宁可不出习题行；
 *   ② 同号取不到（或取到的是模拟卷）→ 按章名主题词匹配（章名去「第X章」前缀后包含于单元名）。
 * 答案只给路径，判分时才读。取不到就返回空——不猜（第十五章没有对应单元，曾错挂期末模拟卷）。
 */
function exerciseFiles(card: SourceCard, cwd: string, row: ChapterRow): { question?: string; answer?: string } {
	if (card.banks.length === 0) return {};

	// README 习题表：单元题目文件 → 该行其余格（含单元标签，如「单元练习十三：权利救济」）
	const labels = new Map<string, string>();
	if (card.dir) {
		try {
			const text = fs.readFileSync(path.join(cwd, card.dir, "README.md"), "utf8");
			for (const line of text.split(/\r?\n/)) {
				if (!line.startsWith("|")) continue;
				const cells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
				const question = cells.find((cell) => /-题目\.md$/.test(cell.replace(/`/g, "")))?.replace(/`/g, "");
				if (!question) continue;
				labels.set(question, cells.filter((cell) => cell.replace(/`/g, "") !== question).join(" "));
			}
		} catch {
			/* 没有 README 或读不了：标签为空，同号命中即用（旧行为） */
		}
	}

	/** 在题库目录里定位这份题目文件；标签是考试卷类 → null（不与章对应）。 */
	const locate = (question: string): { question?: string; answer?: string } | null => {
		const label = labels.get(question);
		if (label && EXAM_LIKE.test(label)) return null;
		for (const bank of card.banks) {
			const relative = bank.path.replace(/\/+$/, "");
			const absolute = path.join(cwd, relative);
			try {
				if (!fs.statSync(absolute).isDirectory()) continue;
				if (!fs.existsSync(path.join(absolute, question))) continue;
			} catch {
				continue;
			}
			const answer = question.replace(/-题目\.md$/, "-答案.md");
			return {
				question: `${relative}/${question}`,
				answer: fs.existsSync(path.join(absolute, answer)) ? `${relative}/${answer}` : undefined,
			};
		}
		return null;
	};

	// ① 同号
	const number = /^(\d+)/.exec(row.file)?.[1];
	if (number) {
		const prefix = new RegExp(`^0*${Number(number)}-`);
		for (const bank of card.banks) {
			const absolute = path.join(cwd, bank.path.replace(/\/+$/, ""));
			let names: string[];
			try {
				if (!fs.statSync(absolute).isDirectory()) continue;
				names = fs.readdirSync(absolute);
			} catch {
				continue;
			}
			const found = names.find((name) => prefix.test(name) && name.endsWith("-题目.md"));
			if (!found) continue;
			const result = locate(found);
			if (result) return result;
		}
	}

	// ② 同号取不到：按章名主题词匹配（「第十三章 权利救济」→「权利救济」）
	const topic = squash(row.chapter).replace(/^第[一二三四五六七八九十百0-9]+章/, "");
	if (topic.length >= 2) {
		for (const [question, label] of labels) {
			if (!squash(label).includes(topic)) continue;
			const result = locate(question);
			if (result) return result;
		}
	}
	return {};
}

/**
 * 本节笔记目录与其中最近的两份——省掉 agent 自己 ls。
 * 目录名先按章名首段（`第十三章 权利救济` → `notes/<卡 notes>/第十三章/`），
 * 章下不建目录的源（如解亘债法按「部」存：`notes/债法总论-解亘/第1部/`）退回按部名首段找。
 */
function noteFiles(card: SourceCard, cwd: string, ...tokens: string[]): { dir?: string; recent: string[] } {
	if (!card.notes) return { recent: [] };
	const root = card.notes.replace(/\/+$/, "");
	for (const raw of tokens) {
		const token = raw.trim().split(/[\s\u3000]+/)[0];
		if (!token) continue;
		const relative = `${root}/${token}`;
		const absolute = path.join(cwd, relative);
		let names: string[];
		try {
			names = fs.readdirSync(absolute).filter((name) => name.endsWith(".md"));
		} catch {
			continue;
		}
		const recent = names
			.map((name) => ({ name, time: fs.statSync(path.join(absolute, name)).mtimeMs }))
			.sort((a, b) => b.time - a.time)
			.slice(0, 2)
			.map((item) => `${relative}/${item.name}`);
		return { dir: relative, recent };
	}
	return { recent: [] };
}

/** 本节的材料行：教材（含页段）／深度层讲义／习题／笔记目录。取不到的项直接不写，不猜。 */
function sectionMaterials(card: SourceCard, cwd: string, row: ChapterRow, rows: ChapterRow[]): string[] {
	const lines: string[] = [];
	if (card.dir) {
		const pages = sectionPages(card, cwd, row, rows);
		lines.push(
			`- 教材：\`${card.dir}/教材/${row.file}\`${pages ? ` · p.${pages}` : ""}——先 grep 节标题「${row.section}」拿行号，只读该节区间`,
		);
	}
	const depth = depthFiles(card, cwd, row.chapter);
	if (depth.length > 0) {
		lines.push(`- 深度层（穿插讲义，按映射）：${depth.map((entry) => `\`${entry}\``).join("、")}`);
	}
	const exercise = exerciseFiles(card, cwd, row);
	if (exercise.question) {
		lines.push(
			`- 习题：\`${exercise.question}\`（题目随时可读；判分时才读答案${exercise.answer ? ` \`${exercise.answer}\`` : ""}）`,
		);
	}
	const notes = noteFiles(card, cwd, row.chapter, row.part);
	if (notes.dir) {
		const recent =
			notes.recent.length > 0
				? `（最近两份：${notes.recent.map((entry) => `\`${path.basename(entry)}\``).join("、")}）`
				: "";
		lines.push(`- 本节笔记：\`${notes.dir}/\`${recent}`);
	}
	return lines;
}

/**
 * 生成「[学习导航]」消息。`extras` ＝ 汇总会话额外要读的全局／各源路径（见 `weeklyPaths`）。
 * 两类会话把「只准读」反过来：汇总（`picked.weekly`）——`学习路线.md`／`进程树.md` 是要读的；设置（`project`）——
 * `.pi/`／`进程树.md`／`学习路线.md`／`agent评估报告.md` 是要读的。两者的末尾那句「不许读」都换成「本会话例外」。
 */
function buildNavMessage(picked: Picked, cwd: string, route: string | undefined, extras: string[] = []): string {
	const { card, mode, subtype, lesson, bank, reading, readingText, chapter, section } = picked;
	const modeLabel = subtype ? `${mode} · ${subtype}` : mode;
	/** 设置会话：跟教学会话相反，项目自身的文件（源卡／skills／子代理／extensions／约定／看板／画像）正是要读的 */
	const project = picked.mode === SETTINGS_MODE && card.modes.includes(SETTINGS_MODE);
	const lines = [`[学习导航] 源：${card.id}（${card.title}）；模式：${modeLabel}`];

	if (picked.weekly) {
		const week = isoWeek(today());
		lines.push(
			`**本次**：本周汇总 ${week.label}（${week.range}）→ 写 \`${WEEKLY_FILE}\` 的「周记」节（本周条目已存在就地更新，不新建）`,
		);
	}
	if (lesson) {
		lines.push(`**本次**：${lesson.label}（${lesson.file}）`);
		if (lesson.extra.length > 0) {
			lines.push(
				"**本次只读**（这一节的料，别的节次一律不碰）：",
				...lesson.extra.map((entry) => `- ${entry}`),
				"（本次之外的不读；确需补某一页的标题/结构时按需 grep 单点，禁整读。）",
			);
		}
	}
	if (bank) {
		lines.push(`**题库**：${bank.path}（${bank.label}）`);
		if (subtype && SUBTYPE_ROUTE[subtype]) lines.push(`**做法**：${SUBTYPE_ROUTE[subtype]}`);
		lines.push("**判分口径**：跟题库自己的 `README.md` 走（硬判分／弹性判分不许混用）。");
	}
	if (section) {
		// 章清单里选中的那一节：教材文件按 `<卡 dir>/教材/` 拼，页码取「页」列
		const file = card.dir ? `${card.dir}/教材/${section.file}` : section.file;
		// 节级行按「教材文件 ＋ 节名」回章清单里对一行（要它的原书页码，算本节页段用）
		const rows = card.chapters ? parseChapters(path.join(cwd, card.chapters)) : [];
		const row = rows.find((item) => item.file === section.file && item.section === section.section) ?? section;
		const pages = card.dir ? sectionPages(card, cwd, row, rows) : section.page;
		lines.push(`**本次**：${chapter ?? section.chapter} · ${section.section}（${file}${pages ? ` · p.${pages}` : ""}）`);
		if (picked.resumed) {
			// 会话可能隔几天才重开：提醒一句以进度文件为准，别把上次的节讲成上一节
			lines.push("（续上会话选中的节；若距上次课已久，精确位置以本源进度文件／章清单状态列为准）");
		}
		// 本节要读的料全在代码里算好（页段／讲次／习题／笔记目录）——agent 不必 ls／find／grep 找路
		const materials = sectionMaterials(card, cwd, row, rows);
		if (materials.length > 0) {
			lines.push(
				"**本节材料**（代码已定位，不必自己找）：",
				...materials,
				"**开讲前只读上面这几份**；skill 里「出题纪律／工具箱／整章收束」那几节、以及任何 `-答案.md`＝用到再读。",
			);
		}
	}
	if (reading) {
		lines.push(`**读法**（用户在菜单里看过，选了「${reading}」）：`, "", readingText ?? "", "");
		if (reading === "调整") {
			lines.push(
				"→ 用户要**调整**读法：先与他商定怎么改，**改完写回该书 `README.md` 的「阅读线读法」节**，再开读。",
				"",
			);
		}
	}
	if (route) lines.push(`**路线**（每周五汇总时的快照，可能滞后；精确位置一律以本源进度文件为准）：${route}`);
	if (lesson || bank || reading || section) lines.push("（上面几行是代码替你定位好的，不必再去翻进度文件确认。）");

	// 汇总／设置两类会话反过来：全局文件与项目自身的文件正是要读的——「只准读」对它们写成「要读」
	const openRead = picked.weekly || project;
	lines.push("", openRead ? "**本会话要读**：" : "**本会话只准读**：");
	const readPaths = openRead ? unique([...allowedPaths(picked), ...extras]) : allowedPaths(picked);
	for (const entry of readPaths) lines.push(`- ${entry}`);
	if (picked.weekly) {
		// 汇总会话相反：全局文件正是要读的（教学会话只写本源进度文件，全局靠这一会话补齐）
		lines.push(
			"",
			`**本会话例外**：跟平时相反——\`${ROUTE_FILE}\`、\`${WEEKLY_FILE}\` 正是你要读的；但只取「本周新增记录／各线一行／周记」需要的部分，**不许整读**教材与笔记正文。`,
		);
	} else if (project) {
		// 设置会话同理：项目自身的文件（源卡／skills／子代理／extensions／约定／看板／画像）正是要读的
		lines.push(
			"",
			`**本会话例外**：跟平时相反——\`.pi/\`（源卡／skills／子代理／extensions／项目约定）、\`${WEEKLY_FILE}\`、\`${ROUTE_FILE}\`、\`agent评估报告.md\` 正是你要读的；但不改各源的教学数据与进度明细，也**不许整读**教材与笔记正文。`,
		);
	} else {
		lines.push(
			"",
			"**不许读**：`学习路线.md`、`进程树.md`、其他源的目录与进度文件——会话开始一律不读；只有收尾更新时才打开它们。",
		);
	}
	lines.push("", `**源卡**（\`${card.file}\`）——按它执行：`, "", card.body);
	return lines.join("\n");
}

// --- 选源 ---

function unique(values: string[]): string[] {
	return Array.from(new Set(values));
}

/** 模式级：卡片里声明到的模式，按 MODE_ORDER 排序，其余排后面。 */
function orderedModes(cards: SourceCard[]): string[] {
	const seen = new Set<string>();
	for (const card of cards) for (const mode of card.modes) seen.add(mode);
	const known = MODE_ORDER.filter((mode) => seen.has(mode));
	const extra = Array.from(seen).filter((mode) => !MODE_ORDER.includes(mode));
	return [...known, ...extra];
}

/** 取 md 里 `## <标题>` 一节的正文（到下一个同级标题为止）。找不到返回 undefined。 */
function readSection(file: string, title: string): string | undefined {
	let text: string;
	try {
		text = fs.readFileSync(file, "utf8");
	} catch {
		return undefined;
	}
	const lines = text.split(/\r?\n/);
	const head = new RegExp(`^##\\s+${title}\\s*$`);
	const start = lines.findIndex((line) => head.test(line.trim()));
	if (start < 0) return undefined;
	const body: string[] = [];
	for (let index = start + 1; index < lines.length; index += 1) {
		if (/^##\s/.test(lines[index])) break;
		body.push(lines[index]);
	}
	return body.join("\n").trim();
}

/**
 * 阅读类：把该书 `README.md` 的「阅读线读法」节摆出来，问「继续 / 调整（/ 回退）」。
 * 选「继续」照读法走；选「调整」先与用户商定怎么改、写回 README 再开读；「回退」＝退回上一级菜单。
 */
async function confirmReading(
	ctx: any,
	card: SourceCard,
	canBack: boolean,
): Promise<{ choice: "继续" | "调整" | "回退"; text: string } | null> {
	const readme = card.dir ? `${card.dir}/README.md` : undefined;
	const text = readme ? readSection(path.join(ctx.cwd, readme), "阅读线读法") : undefined;

	if (!text) {
		ctx.ui.notify(
			readme
				? `${readme} 里没有「阅读线读法」节，先补读法卡再开读`
				: `源卡 ${card.file} 没写 dir:，定位不到读法卡`,
			"warning",
		);
		return { choice: "调整", text: "（读法卡缺失，待补）" };
	}

	const pending = /待定/.test(text);
	const first = pending ? "继续（读法仍是待定，先定下来）" : "继续";
	const options = canBack ? [BACK_LABEL, first, "调整"] : [first, "调整"];
	const chosen = await ctx.ui.select(
		`《${card.title}》怎么读（${readme}）：\n\n${text}\n\n—— 按这个读吗？`,
		options,
	);
	if (!chosen) return null;
	if (canBack && chosen === BACK_LABEL) return { choice: "回退", text };
	return { choice: chosen.startsWith("继续") ? "继续" : "调整", text };
}

/** 菜单级：`ask()` 记「这一级真在菜单里问过」用（自动选中、没弹菜单的不算）。 */
type AskLevel = "subject" | "mode" | "subtype" | "source" | "lesson" | "section";

/**
 * 每一级回退时，由近到远寻找合法的上一级。**自动选中（没弹过菜单）的级直接跳过**——
 * 否则退回去它会被自动重选、同一张菜单再问一遍，死循环（单学科时退「模式」级即此故障：
 * 学科被清后立即自动重选，模式菜单带着回退项反复出现，select 被调用 60+ 次停不下来）。
 * 一级都没问过 → 调用方取消整个选择（不发导航消息）。
 */
const BACK_TARGETS: Record<"mode" | "subtype" | "source", AskLevel[]> = {
	mode: ["subject"],
	subtype: ["mode", "subject"],
	source: ["subtype", "mode", "subject"],
};

type Ask = (
	title: string,
	options: string[],
	level: AskLevel,
	canBackOverride?: boolean,
) => Promise<string | null | undefined>;

/** 课节按「周」分组：周号取自课件文件名开头的 `NN`；组内保持课节顺序，组间按周号升序。 */
function groupByWeek(lessons: Lesson[]): { week: number; lessons: Lesson[] }[] {
	const groups = new Map<number, Lesson[]>();
	for (const lesson of lessons) {
		const week = Number(/^(\d\d)/.exec(path.basename(lesson.file))?.[1] ?? 0);
		const bucket = groups.get(week);
		if (bucket) bucket.push(lesson);
		else groups.set(week, [lesson]);
	}
	return Array.from(groups.entries())
		.sort((a, b) => a[0] - b[0])
		.map(([week, items]) => ({ week, lessons: items }));
}

/** 周菜单项：`第 3 周 · 2 节 · 🔄 进行中`。 */
function weekLabel(group: { week: number; lessons: Lesson[] }): string {
	const mark = group.lessons.some((lesson) => lesson.status === "doing")
		? " · 🔄 进行中"
		: group.lessons.every((lesson) => lesson.status === "done")
			? " · ✅ 已上完"
			: "";
	return `第 ${group.week} 周 · ${group.lessons.length} 节${mark}`;
}

/**
 * 选课节：**先按周分层**（一周里最多两三节，两层菜单都短到不必滚屏），周内只剩一节就直接选中。
 * 回退项由传入的 `ask` 统一处理。返回 Lesson ／ null(回退) ／ undefined(取消)。
 */
async function pickLesson(
	ctx: any,
	card: SourceCard,
	lessons: Lesson[],
	ask: Ask,
): Promise<Lesson | null | undefined> {
	const recommended = recommendIndex(lessons);
	const target = recommended >= 0 ? lessons[recommended] : undefined;
	const groups = groupByWeek(lessons);
	let pool = lessons;

	if (groups.length > 1) {
		const recGroup = groups.find((group) =>
			group.lessons.some((lesson) => lesson.file === target?.file),
		);
		const ordered = recGroup ? [recGroup, ...groups.filter((group) => group !== recGroup)] : groups;
		const labels = ordered.map(
			(group, index) => (index === 0 && recGroup ? `${weekLabel(group)}（推荐）` : weekLabel(group)),
		);
		const picked = await ask(`上哪一周？（${card.title} · 共 ${lessons.length} 份课件）`, labels, "lesson");
		if (picked === undefined) return undefined;
		if (picked === null) return null;
		const group = ordered[labels.indexOf(picked)];
		if (!group) return undefined;
		pool = group.lessons;
	}

	if (pool.length === 1) return pool[0];

	const week = Number(/^(\d\d)/.exec(path.basename(pool[0].file))?.[1] ?? 0);
	const options: string[] = [];
	for (const lesson of pool) {
		if (target && lesson.file === target.file) {
			const why = lesson.status === "doing" ? "接着上次未上完的" : "下一次上这节";
			options.push(`▶ ${lesson.label}（推荐：${why}）`);
		} else {
			options.push(lesson.label);
		}
	}

	const picked = await ask(`上哪一节？（第 ${week} 周 · 共 ${pool.length} 节）`, options, "lesson");
	if (picked === undefined) return undefined;
	if (picked === null) return null;
	return pool.find((lesson) => picked.includes(lesson.label));
}

/**
 * 阅读类：解析章清单（`部｜章｜节｜教材文件｜页｜状态`）成节级行。
 * 反引号单元格＝教材文件（表头与表格前后的说明行都没有它，据此跳过），末列＝状态。
 * 读不到文件、或一行都解析不出，都返回空数组（调用方据此跳过选章这一级）。
 */
function parseChapters(file: string): ChapterRow[] {
	const rows: ChapterRow[] = [];
	let text: string;
	try {
		text = fs.readFileSync(file, "utf8");
	} catch {
		return rows;
	}
	for (const line of text.split(/\r?\n/)) {
		if (!line.startsWith("|")) continue;
		const cells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
		const fileIndex = cells.findIndex((cell) => cell.startsWith("`") && cell.endsWith("`"));
		if (fileIndex < 3) continue;
		const last = cells[cells.length - 1] ?? "";
		const page = cells[fileIndex + 1] ?? "";
		rows.push({
			part: cells[fileIndex - 3],
			chapter: cells[fileIndex - 2],
			section: cells[fileIndex - 1],
			file: cells[fileIndex].slice(1, -1),
			page: /^\d+$/.test(page) ? page : undefined,
			// 阅读线状态列词汇是裸 ✅/⬜/🔄（✅＝读完），与上课线 lessonStatus() 白名单语义不同，勿「统一」。
			status: last.includes("✅") ? "done" : last.includes("🔄") ? "doing" : "todo",
		});
	}
	return rows;
}

/** 一级菜单的一个章：`label` ＝ 菜单里的名字，`rows` ＝ 该章的全部节级行（保持清单顺序）。 */
interface ChapterGroup {
	label: string;
	rows: ChapterRow[];
}

/** 按「部 ＋ 章」去重成章；同名章散在不同部下时标签带部名（`第4部 债的保全 · 第1章 概述`）免得两行一样。 */
function groupChapters(rows: ChapterRow[]): ChapterGroup[] {
	const parts = new Map<string, Set<string>>();
	for (const row of rows) {
		const seen = parts.get(row.chapter) ?? new Set<string>();
		seen.add(row.part);
		parts.set(row.chapter, seen);
	}

	const groups: ChapterGroup[] = [];
	const byKey = new Map<string, ChapterGroup>();
	for (const row of rows) {
		const key = `${row.part}|${row.chapter}`;
		const known = byKey.get(key);
		if (known) {
			known.rows.push(row);
			continue;
		}
		const ambiguous = (parts.get(row.chapter)?.size ?? 0) > 1;
		const group: ChapterGroup = {
			label: ambiguous ? `${row.part} · ${row.chapter}` : row.chapter,
			rows: [row],
		};
		byKey.set(key, group);
		groups.push(group);
	}
	return groups;
}

/** 推荐章：优先接着上次没读完的（该章里有 🔄），否则下一次要读的（第一个含 ⬜ 的章）；全读完返回 -1。 */
function recommendChapter(groups: ChapterGroup[]): number {
	const doing = groups.findIndex((group) => group.rows.some((row) => row.status === "doing"));
	if (doing >= 0) return doing;
	return groups.findIndex((group) => group.rows.some((row) => row.status === "todo"));
}

/**
 * 阅读类：先选章（推荐置顶，同 `pickLesson` 的写法），再选该章的节。
 * 章内只有一行、且节名不是「第 N 节」那种写法（＝「（无节，整章一读）」）时跳过第二级，直接选中那一行。
 * 回退项由传入的 `ask` 统一处理。返回 {章, 节行} ／ null(退章级＝放弃整个章级) ／ undefined(取消)。
 */
async function pickChapter(
	card: SourceCard,
	rows: ChapterRow[],
	ask: Ask,
): Promise<{ chapter: string; section: ChapterRow } | null | undefined> {
	const groups = groupChapters(rows);
	const recommended = recommendChapter(groups);

	for (;;) {
		const options = groups.map((group, index) => {
			if (index !== recommended) return group.label;
			const why = group.rows.some((row) => row.status === "doing")
				? "接着上次未读完的"
				: "下一次读这章";
			return `▶ ${group.label}（推荐：${why}）`;
		});
		const picked = await ask(`读哪一章？（${card.title} · 共 ${groups.length} 章）`, options, "section");
		if (picked === undefined) return undefined;
		if (picked === null) return null;

		const group = groups[options.indexOf(picked)];
		if (!group) return undefined;
		if (group.rows.length === 1 && !/^第\S*节/.test(group.rows[0].section)) {
			return { chapter: group.label, section: group.rows[0] };
		}

		const sections = group.rows.map((row) => row.section);
		const chosen = await ask(`读哪一节？（${group.label} · 共 ${sections.length} 节）`, sections, "section");
		if (chosen === undefined) return undefined;
		if (chosen === null) continue; // 退节：只回到第一级重选章，不清卡
		const hit = group.rows[sections.indexOf(chosen)];
		if (!hit) return undefined;
		return { chapter: group.label, section: hit };
	}
}

/** 菜单里的「回退」项：选中它＝回到上一级。**每级菜单都放在第一项**——长列表滚屏时也不会被挤到屏幕外。 */
const BACK_LABEL = "← 回退";

/**
 * 逐级选：学科 → 模式 →（做题）题型 → 源／题库 →（上课）周／课节 →（阅读）读法确认 →（阅读）章／节。
 * **除第一级外，每一级的第一项都是「← 回退」**（判据＝之前是否已经弹过菜单）：选中即退回上一级重问；
 * `Esc`＝取消整个选择（不发消息）。回退后把该级答案清掉，靠下面的循环重算「下一步该问什么」——不必手写状态机。
 */
async function selectSource(ctx: any, cards: SourceCard[]): Promise<Picked | null> {
	const subjects = unique(cards.map((card) => card.subject));
	/** 已经弹过的菜单：用「弹过几个」判定当前这级是不是第一级（第一级不给回退项）。 */
	const shown: string[] = [];
	/** 真在菜单里问过的级（自动选中、没弹菜单的不算）——回退时只有问过的级才是合法的上一级。 */
	const asked = new Set<AskLevel>();

	/** 弹一步：返回 选中值 ／ null(回退) ／ undefined(取消)。回退项固定放**第一项**。 */
	async function ask(
		title: string,
		options: string[],
		level: AskLevel,
		canBackOverride?: boolean,
	): Promise<string | null | undefined> {
		const canBack = canBackOverride ?? shown.length > 0;
		shown.push(title);
		asked.add(level);
		const list = canBack ? [BACK_LABEL, ...options] : options;
		const chosen = await ctx.ui.select(title, list);
		if (chosen === undefined) return undefined;
		return canBack && chosen === BACK_LABEL ? null : chosen;
	}

	/**
	 * 回退一步：作废 `from` 这一级及以下的答案，再往上找**真问过**的最近一级重问
	 * （自动选中的级直接跳过，见 BACK_TARGETS 注释）；一级都没问过 → null（取消）。
	 */
	function backFrom(from: "mode" | "subtype" | "source"): "continue" | null {
		clearFrom(from);
		for (const target of BACK_TARGETS[from]) {
			if (!asked.has(target)) continue;
			clearFrom(target);
			return "continue";
		}
		return null;
	}

	/** 作废 level 及以下的全部答案（多清的本就是空值，无害；靠下面的循环重算下一步）。 */
	function clearFrom(level: "subject" | "mode" | "subtype" | "source"): void {
		if (level === "subject") state.subject = undefined;
		if (level === "subject" || level === "mode") state.mode = undefined;
		if (level === "subject" || level === "mode" || level === "subtype") state.subtype = undefined;
		state.card = undefined;
		state.bank = undefined;
		state.lesson = undefined;
		state.reading = undefined;
		state.readingText = undefined;
		state.chapter = undefined;
		state.section = undefined;
	}

	const state: {
		subject?: string;
		mode?: string;
		subtype?: string;
		card?: SourceCard;
		bank?: Bank;
		lesson?: Lesson;
		reading?: "继续" | "调整";
		readingText?: string;
		chapter?: string;
		section?: ChapterRow;
	} = {};

	for (;;) {
		// 一、学科（只有一个学科就不问；问了它就是第一级）
		if (!state.subject) {
			if (subjects.length > 1) {
				const picked = await ask("学哪科？", subjects, "subject");
				if (picked === undefined || picked === null) return null;
				state.subject = picked;
			} else {
				state.subject = subjects[0];
			}
		}

		// 二、模式（上课 / 阅读 / 做题 / 汇总 …）
		const modes = orderedModes(cards.filter((card) => card.subject === state.subject));
		if (!state.mode) {
			if (modes.length > 1) {
				// 该推荐汇总时把它挪到第一位；标签与模式值一一对应（标签变了，所以按索引取回真正的模式值，别去反查）
				const nudge = modes.includes(WEEKLY_MODE) && shouldNudgeWeekly(ctx.cwd, today());
				const values = modes.slice();
				const labels = modes.slice();
				if (nudge) {
					const index = values.indexOf(WEEKLY_MODE);
					values.splice(index, 1);
					labels.splice(index, 1);
					const week = isoWeek(today());
					values.unshift(WEEKLY_MODE);
					labels.unshift(`${WEEKLY_MODE}（推荐 · 本周汇总还没记：${week.label} ${week.range}）`);
				}
				const picked = await ask("今天做什么？", labels, "mode", asked.has("subject"));
				if (picked === undefined) return null;
				if (picked === null) {
					// 回退到学科；单学科时学科是自动选中的（没问过）→ 没有上一级，取消，别无限重问
					if (backFrom("mode") === null) return null;
					continue;
				}
				state.mode = values[labels.indexOf(picked)];
			} else {
				state.mode = modes[0];
			}
			if (!state.mode) return null;
		}
		const mode = state.mode;

		// 三、题型（只有做题有）
		const subtypes = SUBTYPES[mode] ?? [];
		if (subtypes.length > 0 && !state.subtype) {
			if (subtypes.length > 1) {
				const picked = await ask("做哪种题？", subtypes, "subtype");
				if (picked === undefined) return null;
				if (picked === null) {
					if (backFrom("subtype") === null) return null;
					continue;
				}
				state.subtype = picked;
			} else {
				state.subtype = subtypes[0];
			}
		}

		// 四、源。做题＝选题库（把「卡 × banks」展平，他选的是题库不是书）；其余＝按模式过滤后的源
		const inMode = cards.filter((card) => card.subject === state.subject && card.modes.includes(mode));
		const bankEntries: { card: SourceCard; bank: Bank }[] = [];
		if (mode === "做题") {
			for (const card of inMode) for (const bank of card.banks) bankEntries.push({ card, bank });
			if (bankEntries.length === 0) {
				ctx.ui.notify("没有源卡声明题库（`banks`），先去卡里加", "warning");
				return null;
			}
		}
		const bankLabels = bankEntries.map((item) =>
			item.bank.label === item.card.title ? item.bank.label : `${item.bank.label} · ${item.card.title}`,
		);
		/** 源这一步是否真在菜单里问（不问＝自动选中；回退目标由 `asked` 判定，见 backFrom） */
		const sourceAsked = mode === "做题" ? bankEntries.length > 1 : inMode.length > 1;

		if (!state.card) {
			if (mode === "做题") {
				if (!sourceAsked) {
					state.card = bankEntries[0].card;
					state.bank = bankEntries[0].bank;
				} else {
					const picked = await ask(`做哪套题库？（${state.subtype ?? mode}）`, bankLabels, "source");
					if (picked === undefined) return null;
					if (picked === null) {
						// 回退到题型（做题必有题型级）
						if (backFrom("subtype") === null) return null;
						continue;
					}
					const hit = bankEntries[bankLabels.indexOf(picked)];
					if (!hit) return null;
					state.card = hit.card;
					state.bank = hit.bank;
				}
			} else if (inMode.length === 1) {
				state.card = inMode[0];
			} else if (inMode.length > 1) {
				const labels = inMode.map((item) => item.title);
				const picked = await ask(`读哪本 / 上哪门课？（${state.subject} · ${mode}）`, labels, "source");
				if (picked === undefined) return null;
				if (picked === null) {
					// 回退到题型；该模式没有题型级（阅读/上课/汇总）时自动跳到模式级
					if (backFrom("subtype") === null) return null;
					continue;
				}
				const found = inMode[labels.indexOf(picked)];
				if (!found) return null;
				state.card = found;
			} else {
				return null;
			}
		}

		// 五、上课类：选课节（推荐＝清单第一个 🔄，否则第一个 ⬜）
		if (state.card.lectures && !state.lesson) {
			const lessons = listLessons(state.card, ctx.cwd);
			if (lessons.length === 0) {
				ctx.ui.notify(
					`${state.card.lectures}/ 里没找到《${state.card.title}》的课件，先投放 PPT`,
					"warning",
				);
			} else if (lessons.length === 1) {
				state.lesson = lessons[0];
			} else {
				const picked = await pickLesson(ctx, state.card, lessons, ask);
				if (picked === undefined) return null;
				if (picked === null) {
					// 退课节：卡一律清掉——回退目标由 backFrom 找「真问过的级」，不会把这张卡粘住
					if (backFrom("source") === null) return null;
					continue;
				}
				state.lesson = picked;
			}
		}

		// 六、阅读类：把该书读法摆出来，问「继续 / 调整（/ 回退）」
		if (mode === "阅读" && !state.reading) {
			const confirmed = await confirmReading(ctx, state.card, shown.length > 0);
			if (!confirmed) return null;
			if (confirmed.choice === "回退") {
				// 退读法确认：卡一律清掉——回退目标由 backFrom 找「真问过的级」
				if (backFrom("source") === null) return null;
				continue;
			}
			state.reading = confirmed.choice;
			state.readingText = confirmed.text;
		}

		// 七、阅读类：选章 → 选节（卡里给了 `chapters:` 才问；读不到章清单就跳过这一级，不拦人）
		if (mode === "阅读" && state.card.chapters && !state.section) {
			const rows = parseChapters(path.join(ctx.cwd, state.card.chapters));
			if (rows.length === 0) {
				ctx.ui.notify(
					`${state.card.chapters} 读不到或解析不出章清单（《${state.card.title}》），跳过选章`,
					"warning",
				);
			} else {
				const picked = await pickChapter(state.card, rows, ask);
				if (picked === undefined) return null;
				if (picked === null) {
					// 退章级：卡一律清掉——回退目标由 backFrom 找「真问过的级」
					if (backFrom("source") === null) return null;
					continue;
				}
				state.chapter = picked.chapter;
				state.section = picked.section;
			}
		}

		return {
			card: state.card,
			mode,
			subtype: state.subtype,
			bank: state.bank,
			lesson: state.lesson,
			reading: state.reading,
			readingText: state.readingText,
			chapter: state.chapter,
			section: state.section,
			weekly: mode === WEEKLY_MODE && state.card.modes.includes(WEEKLY_MODE),
		};
	}
}

interface Recalled {
	card: SourceCard;
	mode?: string;
	subtype?: string;
	bankPath?: string;
	/** 阅读类：上次选中的章名与节级行（resume 时续上，agent 不必重新定位） */
	chapter?: string;
	section?: ChapterRow;
	reading?: "继续" | "调整";
	readingText?: string;
}

/** 记住本会话的选择（session_start 与 /source 都会写），resume 时据此直接续注入。 */
function recallSource(ctx: any, cards: SourceCard[]): Recalled | undefined {
	let data:
		| {
				id?: string;
				mode?: string;
				subtype?: string;
				bank?: string;
				chapter?: string;
				section?: ChapterRow;
				reading?: "继续" | "调整";
				readingText?: string;
		  }
		| undefined;
	try {
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type === "custom" && entry.customType === ENTRY_TYPE) {
				const found = entry.data as typeof data;
				if (found?.id) data = found;
			}
		}
	} catch {
		return undefined;
	}
	const card = data?.id ? cards.find((item) => item.id === data?.id) : undefined;
	return card
		? {
				card,
				mode: data?.mode,
				subtype: data?.subtype,
				bankPath: data?.bank,
				chapter: data?.chapter,
				section: data?.section,
				reading: data?.reading,
				readingText: data?.readingText,
			}
		: undefined;
}

// --- 自动打开课件 ---

/** Edge 可执行文件路径（Windows）。 */
const EDGE_EXE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

/**
 * 用 Edge 打开课件 PDF（仅 zf-zhang / mz-zhang 两张卡）。
 * 异步执行，不阻塞导航消息发送；打开失败只记 notify，不抛错。
 */
function openWithEdge(ctx: any, absolutePath: string): void {
	if (!fs.existsSync(absolutePath)) {
		ctx.ui.notify(`课件不存在：${absolutePath}`, "warning");
		return;
	}
	const cmd = `start "" "${EDGE_EXE}" "${absolutePath}"`;
	exec(cmd, (error) => {
		if (error) ctx.ui.notify(`Edge 打开课件失败：${error.message}`, "warning");
	});
}

export default function (pi: ExtensionAPI) {
	function announce(picked: Picked, ctx: any, cards: SourceCard[]): void {
		const route = picked.card.route ? routeLine(ctx.cwd, picked.card.route) : undefined;
		// 汇总会话要多读全局文件与各源进度：路径由代码算好塞进导航消息（教学会话不带 extras）
		const extras = picked.weekly ? weeklyPaths(cards) : undefined;
		pi.appendEntry(ENTRY_TYPE, {
			id: picked.card.id,
			mode: picked.mode,
			subtype: picked.subtype,
			lesson: picked.lesson?.file,
			bank: picked.bank?.path,
			// 阅读类续上：章/节/读法一并记住，resume 时原样续注入（含「本节材料」整段）
			chapter: picked.chapter,
			section: picked.section,
			reading: picked.reading,
			readingText: picked.readingText,
		});
		// 张焕然两门上课线：选完课节后自动用 Edge 打开对应课件 PDF
		if (picked.mode === "上课" && picked.lesson && (picked.card.id === "zf-zhang" || picked.card.id === "mz-zhang")) {
			const file = path.join(ctx.cwd, picked.lesson.file);
			openWithEdge(ctx, file);
		}
		pi.sendUserMessage(buildNavMessage(picked, ctx.cwd, route, extras));
	}

	pi.on("session_start", async (event, ctx) => {
		if (!GREET_REASONS.has(event.reason)) return;
		if (ctx.mode !== "tui" || !ctx.hasUI) return;
		if (!ctx.isIdle()) return;

		const cards = loadSources(ctx.cwd);
		if (cards.length === 0) return;

		const remembered = recallSource(ctx, cards);
		if (remembered) {
			// 续本会话的选择：模式/题型/题库沿用；上课类顺手把「接着上哪节」算出来；
			// 阅读类连章/节/读法一起续上（resume 也有完整的「本次」与「本节材料」段）
			const mode = remembered.mode ?? remembered.card.modes[0] ?? "阅读";
			const lessons = listLessons(remembered.card, ctx.cwd);
			const index = lessons.length > 0 && mode === "上课" ? recommendIndex(lessons) : -1;
			announce(
				{
					card: remembered.card,
					mode,
					subtype: remembered.subtype,
					bank: remembered.bankPath
						? remembered.card.banks.find((item) => item.path === remembered.bankPath)
						: undefined,
					lesson: index >= 0 ? lessons[index] : undefined,
					chapter: remembered.chapter,
					section: remembered.section,
					reading: remembered.reading,
					readingText: remembered.readingText,
					resumed: true,
					weekly: mode === WEEKLY_MODE && remembered.card.modes.includes(WEEKLY_MODE),
				},
				ctx,
				cards,
			);
			return;
		}

		const picked = await selectSource(ctx, cards);
		if (!picked) return;
		announce(picked, ctx, cards);
	});

	pi.registerCommand("source", {
		description:
			"重选学习源（先选上课/阅读/做题〔选择题/案例题〕，再选哪本/哪门课/哪套题库），并把该源的卡与只读清单重新注入本会话",
		handler: async (_args, ctx: any) => {
			if (typeof ctx.isIdle === "function" && !ctx.isIdle()) {
				ctx.ui.notify("等 agent 忙完再换源", "warning");
				return;
			}
			const cards = loadSources(ctx.cwd);
			if (cards.length === 0) {
				ctx.ui.notify(`没找到源卡：${SOURCES_DIR}/ 下没有可用的 .md`, "warning");
				return;
			}
			const picked = await selectSource(ctx, cards);
			if (!picked) return;
			announce(picked, ctx, cards);
		},
	});

	// /weekly：不等周五，随时开一个汇总会话（菜单里的「汇总」与它同一条路）
	const weekly = {
		description: `把本周「做了什么」记进 ${WEEKLY_FILE} 的周记节（每周五汇总；也随时可手动跑）`,
		handler: async (_args: any, ctx: any) => {
			if (typeof ctx.isIdle === "function" && !ctx.isIdle()) {
				ctx.ui.notify("等 agent 忙完再记总账", "warning");
				return;
			}
			const cards = loadSources(ctx.cwd);
			const card = cards.find((item) => item.modes.includes(WEEKLY_MODE));
			if (!card) {
				ctx.ui.notify(`没有「${WEEKLY_MODE}」源卡（${SOURCES_DIR}/weekly.md），先建卡`, "warning");
				return;
			}
			announce({ card, mode: WEEKLY_MODE, weekly: true }, ctx, cards);
		},
	};
	pi.registerCommand("weekly", weekly);
	try {
		// pi 若不接受非 ASCII 命令名（抛错或忽略），也不能让整个扩展加载失败
		pi.registerCommand(WEEKLY_MODE, weekly);
	} catch {
		/* 中文命令名注册不上就算了，/weekly 照旧 */
	}
}
