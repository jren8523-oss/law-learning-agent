/**
 * opening-greeting — 打开 pi 时自动显示「学习导航」。
 *
 * 用户一天可能打开多次；本扩展在 session_start（启动/新会话/恢复）时读
 * 当前教材的进度文件，把「上次讲到哪 + 有没有久未触及 + 学习菜单」拼成
 * 一条导航消息，用 sendMessage({ display: true }) 直接显示在界面上——
 * 不用等用户先打一句话。
 *
 * 数据来源：
 *   - 学习路线.md：§六「最近完成 / 下一课」（教学顺序唯一权威来源，进度只此一家）
 *   - kb/<书>/复习队列.md：复习队列的「最近触及」列（做久未触及检测）
 *   - profile.md：当前教材名（定位课程进度文件）
 *
 * 久未触及阈值 STALE_DAYS = 7（约一周），改这里即可。
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Box, Text } from "@earendil-works/pi-tui";
import * as fs from "node:fs";
import * as path from "node:path";

const GREET_REASONS = new Set(["startup", "new", "resume"]);
const STALE_DAYS = 7;

function readFile(p: string): string | null {
	try {
		return fs.readFileSync(p, "utf-8");
	} catch {
		return null;
	}
}

function todayISO(): string {
	const d = new Date();
	const y = d.getFullYear();
	const m = String(d.getMonth() + 1).padStart(2, "0");
	const day = String(d.getDate()).padStart(2, "0");
	return `${y}-${m}-${day}`;
}

function daysAgoISO(iso: string): number {
	const t = new Date(`${iso}T00:00:00`).getTime();
	const now = new Date(`${todayISO()}T00:00:00`).getTime();
	return Math.round((now - t) / 86400000);
}

// 从 学习路线.md 的「六、当前状态」取定位信息——该文件是教学顺序的唯一权威来源，
// 进度只在那一处写；此处不再解析 进程树.md（避免权威源与读取源分家导致漂移）。
function routeStatus(route: string): { lastDone: string; nextLesson: string } {
	const pick = (label: string): string => {
		const re = new RegExp(`^-\\s*\\*\\*${label}\\*\\*[：:]\\s*(.+)$`, "m");
		const m = re.exec(route);
		return (m?.[1] || "").replace(/\s*✅\s*$/, "").replace(/\*\*/g, "").trim();
	};
	return { lastDone: pick("最近完成"), nextLesson: pick("下一课") };
}

// 从 课程进度.md 的复习队列表抽「最近触及」日期，返回超过阈值的主题列表。
function staleTopics(progress: string): string[] {
	const out: string[] = [];
	const re = /^\|\s*([^|]+?)\s*\|\s*(?:法条|概念|类型摇摆)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|/gm;
	let m: RegExpExecArray | null;
	while ((m = re.exec(progress)) !== null) {
		const topic = m[1].trim();
		const date = m[2];
		if (topic && daysAgoISO(date) > STALE_DAYS) out.push(topic);
	}
	return out;
}

function currentBook(profile: string): string {
	const m = /当前教材[：:]\s*([^（(]+)/.exec(profile);
	return (m?.[1] || "民法总论").trim();
}

function buildContent(cwd: string): string {
	const profile = readFile(path.join(cwd, "profile.md")) || "";
	const book = currentBook(profile);
	const route = readFile(path.join(cwd, "学习路线.md")) || "";
	const progress = readFile(path.join(cwd, "kb", book, "复习队列.md")) || "";

	const { lastDone, nextLesson } = routeStatus(route);
	const stale = staleTopics(progress);

	const lines: string[] = [];

	if (stale.length > 0) {
		const sample = stale
			.slice(0, 2)
			.map((t) => `「${t}」`)
			.join(" ");
		const more = stale.length > 2 ? " …" : "";
		lines.push(`⚠️ 有 ${stale.length} 个主题约一周没碰了：${sample}${more}，要不要先顺一遍？`);
	}
	if (lastDone) lines.push(`上次讲完：${lastDone}`);
	if (nextLesson) lines.push(`下一课：${nextLesson}`);
	if (lines.length === 0) lines.push("继续学习吧。");

	lines.push("");
	lines.push("今天想怎么学？");
	lines.push("1. 继续上课 → 说“继续”");
	lines.push("2. 学新章节 → 说“学第 X 章”");
	lines.push("3. 拷问/刷题 → 说“拷问我” / “刷 N 题”");
	lines.push("4. 练案例 → 说“练案例”");
	lines.push("5. 回顾 → 说“复习”");
	lines.push("6. 调整 agent / 架构 / 设置 → 说“设置”");

	return lines.join("\n");
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (event: any, ctx: any) => {
		if (!GREET_REASONS.has(event?.reason)) return;

		const cwd = (ctx as any)?.cwd || process.cwd();
		const content = buildContent(cwd);

		await pi.sendMessage({
			customType: "opening-greeting",
			content,
			display: true,
		});
	});

	pi.registerMessageRenderer("opening-greeting", (message: any, { outputPad }: any, theme: any) => {
		const box = new Box(outputPad, 1, (t: any) => theme.bg("customMessageBg", t));
		box.addChild(new Text(theme.fg("accent", theme.bold("📖 学习导航")), 0, 0));
		box.addChild(new Text(String(message.content), 0, 0));
		return box;
	});
}
