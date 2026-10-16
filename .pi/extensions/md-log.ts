/**
 * md-log — mirror the session to a markdown file for comfortable reading.
 *
 * Designed for long teaching/learning sessions where the terminal is hard on
 * the eyes and markdown/math/code don't render. The linked .md file is meant
 * to be viewed rendered (e.g. in Obsidian), so assistant text with $...$ math,
 * code blocks, and markdown all render natively — no rendering work here.
 *
 * Captures only reading-relevant content:
 *   - user prompts
 *   - assistant text (lesson prose)
 *   - quiz / ask_user_question Q&A blocks
 * Other tools (bash, read, write, edit, ...) are omitted.
 *
 * Quiz/ask questions are written BEFORE the user answers (on tool_call), so the
 * reader sees the question appear live; the answer + feedback are appended on
 * tool_result. The question block NEVER contains the correct answer or
 * explanation (the user reads this file live).
 *
 * Commands:
 *   /md-log <filepath>  — Link a markdown file and backfill the session.
 *   /md-unlog           — Stop logging.
 * Tool:
 *   md_log { action, filepath? } — same linking, callable by the agent, so a
 *   lesson archive starts without any user action. Paths under notes/ are
 *   auto-created (parents included); other paths must already exist.
 *
 * Append-only. No send-back-to-agent functionality (that lived in the old
 * .md-link extension this was modeled on).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import { Type } from "typebox";

const QA_TOOLS = new Set(["quiz", "ask_user_question"]);

export default function mdLog(pi: ExtensionAPI) {
	let logFile: string | null = null;

	// --- State restoration on session restart ---

	pi.on("session_start", async (_event, ctx) => {
		let lastLinkData: { file: string | null } | undefined;
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type === "custom" && entry.customType === "md-log") {
				lastLinkData = entry.data as { file: string | null } | undefined;
			}
		}
		if (lastLinkData?.file) {
			logFile = lastLinkData.file;
			const theme = ctx.ui.theme;
			ctx.ui.setStatus(
				"md-log",
				theme.fg("accent", "🗒 ") + theme.fg("dim", path.basename(logFile)),
			);
		}
	});

	// --- Serialization: events can fire close together; keep appends ordered ---

	let writeLock: Promise<void> = Promise.resolve();
	function withLock<T>(fn: () => T | Promise<T>): Promise<T> {
		const prev = writeLock;
		let release: () => void;
		writeLock = new Promise<void>((r) => {
			release = r;
		});
		return prev.then(fn).finally(() => release!());
	}

	function appendToFile(text: string): void {
		if (!logFile) return;
		try {
			let current = "";
			if (fs.existsSync(logFile)) {
				current = fs.readFileSync(logFile, "utf-8");
			}
			const prefix = current.trim().length > 0 ? "\n\n" : "";
			fs.writeFileSync(logFile, current + prefix + text + "\n", "utf-8");
		} catch {
			// File may have been deleted externally; ignore.
		}
	}

	// --- Formatting ---

	function callout(type: string, title: string, bodyLines: string[]): string {
		const lines = [`> [!${type}] ${title}`];
		for (const line of bodyLines) {
			lines.push(line.length === 0 ? ">" : `> ${line}`);
		}
		return lines.join("\n");
	}

	function userBlock(text: string): string {
		return `> [!quote] YOU\n\n${text}`;
	}

	// Skill declarations (`<skill name="..." ...> ...whole SKILL.md... </skill>`)
	// are system-injected context, not user prose. Replace each with a compact
	// callout noting the skill was loaded, so the log keeps the signal without
	// the noise. Runs on already-trimmed text.
	function stripSkillBlocks(text: string): string {
		return text.replace(
			/<skill\b([^>]*)>[\s\S]*?<\/skill>/g,
			(_match, attrs: string) => {
				const name = /name="([^"]+)"/.exec(attrs)?.[1];
				return `> [!note] SKILL loaded: ${name ?? "(unknown)"}`;
			},
		);
	}

function assistantBlock(text: string): string {
	return `> [!abstract] PI\n\n${text}`;
}

// Second line of defence for literal "\n" sequences. quiz.ts now normalizes
// them at the entry point, but details persisted in OLDER sessions still carry
// the double-escaped form, and backfill replays those verbatim. Clean here too
// so replayed history renders with real paragraph breaks.
function normalizeEscapedNewlines(text: string): string {
	return text.replace(/\\n/g, "\n");
}

	function optionsList(options: Array<{ label: string }>): string[] {
		return options.map((o, i) => `${i + 1}. ${o.label}`);
	}

	function questionCallout(label: string, question: string, context: string | undefined, options: Array<{ label: string }>): string {
		const body: string[] = [];
		for (const line of question.split("\n")) body.push(line);
		if (context) {
			body.push("");
			for (const line of context.split("\n")) body.push(line);
		}
		if (options.length > 0) {
			body.push("");
			body.push(...optionsList(options));
		}
		return callout("question", label, body);
	}

	function answerCalloutQuiz(details: any): string {
		const status = details?.status;
		if (status === "cancelled") {
			return callout("warning", "Quiz — cancelled", ["(user skipped)"]);
		}
		if (status === "unavailable") {
			return callout("warning", "Quiz — unavailable", [details?.message || ""]);
		}
		// "I don't know" is neither correct nor incorrect — it's a distinct signal,
		// so it never renders as a red ✗.
		const dontKnow = details?.dontKnow === true;
		const correct = details?.correct === true;
		const type = dontKnow ? "question" : correct ? "success" : "failure";
		const title = dontKnow
			? "Quiz — I don't know"
			: correct
				? "Quiz — correct ✓"
				: "Quiz — incorrect ✗";
		const body: string[] = [];

		if (dontKnow) {
			body.push("Your answer: I don't know");
		} else {
			const answers: any[] = details?.answers || [];
			const sel = answers.map((a) => `${a.index}. ${a.label}`).join(", ") || "(none)";
			body.push(`Your answer: ${sel}`);
		}

		const correctIndices: number[] = details?.correctIndices || [];
		// 索引用乱序后的显示序还原成「N. 标签」——与上面 Your answer 行同构；
		// 选项被 quiz 打乱过，光写数字读者得数回原始列表（P1-16）。
		const displayed: Array<{ index: number; label: string }> = details?.options || [];
		const correctStr = correctIndices
			.map((i) => {
				const opt = displayed.find((o) => o.index === i);
				return opt ? `${i}. ${opt.label}` : `${i}`;
			})
			.join(", ");
		body.push(`Correct answer: ${correctStr}`);

		// Optional free-text note the user typed in the always-present note field.
		// Only present (in details) when non-empty, so no guard for empty strings.
		if (details?.note) {
			body.push("");
			const noteLines = String(details.note).split("\n");
			body.push(`Note: ${noteLines[0]}`);
			for (let i = 1; i < noteLines.length; i++) body.push(noteLines[i]);
		}

		if (details?.explanation) {
			body.push("");
			const cleaned = normalizeEscapedNewlines(String(details.explanation));
			for (const line of cleaned.split("\n")) body.push(line);
		}
		return callout(type, title, body);
	}

	function answerCalloutAsk(details: any): string {
		const status = details?.status;
		if (status === "cancelled") {
			return callout("warning", "Question — cancelled", ["(user skipped)"]);
		}
		if (status === "unavailable") {
			return callout("warning", "Question — unavailable", [details?.message || ""]);
		}
		const answers: any[] = details?.answers || [];
		const body: string[] = answers.map((a) => {
			if (a.type === "other") return `Other: ${a.label}`;
			if (a.type === "text") return a.label;
			return `${a.index}. ${a.label}`;
		});
		if (body.length === 0) body.push("(no answer)");
		return callout("example", "Answer", body);
	}

	// --- Event handlers ---

	pi.on("message_end", async (event, _ctx) => {
		if (!logFile) return;
		const msg = event.message;
		if (!msg || !("role" in msg)) return;

		if (msg.role === "user") {
			const text = typeof msg.content === "string"
				? msg.content
				: Array.isArray(msg.content)
					? msg.content.filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n")
					: "";
			const trimmed = stripSkillBlocks(text.trim());
			if (!trimmed) return;
			await withLock(() => appendToFile(userBlock(trimmed)));
			return;
		}

		if (msg.role === "assistant") {
			const textParts = (msg.content || [])
				.filter((c: any) => c.type === "text")
				.map((c: any) => (c.text as string).trim())
				.filter((t: string) => t.length > 0);
			if (textParts.length === 0) return;
			await withLock(() => appendToFile(assistantBlock(textParts.join("\n\n"))));
			return;
		}
		// toolResult messages are handled by the tool_result event (for QA tools).
	});

	// ask_user_question never shuffles its options, so the tool_call args are
	// already the true display order — safe to write the question live, before
	// the user answers.
	pi.on("tool_call", async (event, _ctx) => {
		if (!logFile) return;
		const toolName = (event as any).toolName;
		if (toolName !== "ask_user_question") return;
		const input = (event as any).input || {};
		const question: string = input.question || "";
		const context: string | undefined = input.details?.trim() || undefined;
		const options: Array<{ label: string }> = Array.isArray(input.options) ? input.options : [];
		const block = questionCallout("Question", question, context, options);
		await withLock(() => appendToFile(block));
	});

	// quiz DOES shuffle its options inside execute(), so the tool_call args are
	// the pre-shuffle author order — NOT what the user is shown. quiz emits an
	// onUpdate() with the true (post-shuffle) order before it blocks on the
	// user's answer; wait for that instead so the logged order always matches
	// what's on screen. Guard against duplicate writes if multiple updates fire
	// for the same call.
	const loggedQuizQuestion = new Set<string>();
	pi.on("tool_execution_update", async (event, _ctx) => {
		if (!logFile) return;
		const toolName = (event as any).toolName;
		if (toolName !== "quiz") return;
		const toolCallId = (event as any).toolCallId;
		if (loggedQuizQuestion.has(toolCallId)) return;
		const shuffled = (event as any).partialResult?.details?.options as Array<{ index: number; label: string }> | undefined;
		if (!shuffled || shuffled.length === 0) return;
		loggedQuizQuestion.add(toolCallId);
		const input = (event as any).args || {};
		const question: string = input.question || "";
		const context: string | undefined = input.details?.trim() || undefined;
		const options = shuffled.map((o) => ({ label: o.label }));
		const block = questionCallout("Quiz", question, context, options);
		await withLock(() => appendToFile(block));
	});

	pi.on("tool_result", async (event, _ctx) => {
		if (!logFile) return;
		const toolName = (event as any).toolName;
		if (!QA_TOOLS.has(toolName)) return;
		const details = (event as any).details;
		const block = toolName === "quiz"
			? answerCalloutQuiz(details)
			: answerCalloutAsk(details);
		await withLock(() => appendToFile(block));
	});

	// --- Shared link logic (used by the /md-log command and the md_log tool) ---

	// Auto-create is allowed only under <cwd>/notes/: the note archive is the
	// intended destination, so a not-yet-existing note there is created on the
	// fly (parents included). Any other path keeps the anti-typo guard.
	function resolveLinkTarget(filepath: string, cwd: string): { resolved?: string; error?: string } {
		const resolved = path.isAbsolute(filepath) ? filepath : path.resolve(cwd, filepath);
		if (!fs.existsSync(resolved)) {
			const notesRoot = path.resolve(cwd, "notes");
			if (!resolved.startsWith(notesRoot + path.sep)) {
				return { error: `File does not exist (auto-create only under notes/): ${resolved}` };
			}
			try {
				fs.mkdirSync(path.dirname(resolved), { recursive: true });
				fs.writeFileSync(resolved, "", "utf-8");
			} catch (e) {
				return { error: `Could not create: ${resolved} (${(e as Error).message})` };
			}
		}
		if (!fs.statSync(resolved).isFile()) {
			return { error: `Not a file: ${resolved}` };
		}
		return { resolved };
	}

	function linkFile(resolved: string, ctx: any): number {
		logFile = resolved;
		pi.appendEntry("md-log", { file: resolved });
		const written = backfill(ctx);
		const theme = ctx.ui?.theme;
		if (theme) {
			ctx.ui.setStatus("md-log", theme.fg("accent", "🗒 ") + theme.fg("dim", path.basename(resolved)));
		}
		return written;
	}

	function unlinkFile(ctx: any): string | null {
		if (!logFile) return null;
		const name = logFile;
		logFile = null;
		pi.appendEntry("md-log", { file: null });
		ctx.ui?.setStatus?.("md-log", undefined);
		return name;
	}

	// --- Commands ---

	pi.registerCommand("md-log", {
		description: "Mirror the session to a markdown file (auto-creates under notes/, backfills history)",
		handler: async (args, ctx: any) => {
			const filepath = args.trim();
			if (!filepath) {
				ctx.ui.notify("Usage: /md-log <filepath>", "warning");
				return;
			}
			if (typeof ctx.isIdle === "function" && !ctx.isIdle()) {
				ctx.ui.notify("Wait for the agent to finish before linking.", "warning");
				return;
			}

			const target = resolveLinkTarget(filepath, ctx.cwd);
			if (target.error) {
				ctx.ui.notify(target.error, "error");
				return;
			}
			const resolved = target.resolved!;

			// Re-running /md-log on the same file within one session must be a
			// no-op: live handlers are already mirroring, and backfilling again
			// would append the whole history a second time (append-only).
			if (logFile === resolved) {
				ctx.ui.notify(`Already linked: ${resolved}`, "info");
				return;
			}

			const written = linkFile(resolved, ctx);
			ctx.ui.notify(`Linked: ${resolved} (${written} entries backfilled)`, "success");
		},
	});

	pi.registerCommand("md-unlog", {
		description: "Stop mirroring the session to a markdown file",
		handler: async (_args, ctx) => {
			const name = unlinkFile(ctx);
			if (name === null) {
				ctx.ui.notify("No file linked", "warning");
				return;
			}
			ctx.ui.notify(`Unlinked: ${path.basename(name)}`, "info");
		},
	});

	// --- Tool: agent-driven linking, so archiving needs no user action ---
	// The agent links a note right when a lesson starts; from then on the
	// event handlers mirror the session live, exactly as with /md-log.

	pi.registerTool({
		name: "md_log",
		label: "md-log",
		description:
			"Link (or unlink) the markdown file that mirrors this session — user prompts, assistant text, and quiz/ask_user_question Q&A are appended live. When a teaching or practice session begins, proactively link a note at notes/<书>/<章>/<日期>-<主题>.md so the lesson is archived without any user action. Files under notes/ are created automatically (including parent directories); paths outside notes/ must already exist.",
		promptSnippet:
			"Use md_log to link the session-mirror note when a lesson starts; it mirrors live afterwards.",
		promptGuidelines: [
			"Link once, right when teaching starts: md_log(action=\"link\", filepath=\"notes/<书>/<章>/<日期>-<主题>.md\").",
			"Paths under notes/ are auto-created; anything outside notes/ must already exist.",
			"Never put a quiz answer into the note's file name; the log itself never contains answers before the user answers.",
		],
		parameters: Type.Object({
			action: Type.Union([Type.Literal("link"), Type.Literal("unlink"), Type.Literal("status")], {
				description: '"link" starts mirroring to filepath, "unlink" stops, "status" reports the current target.',
			}),
			filepath: Type.Optional(
				Type.String({ description: "Required for link. Relative paths resolve against the project root." }),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (params.action === "status") {
				const text = logFile ? `Currently linked: ${logFile}` : "No file linked";
				return { content: [{ type: "text" as const, text }] };
			}
			if (params.action === "unlink") {
				const name = unlinkFile(ctx);
				const text = name === null ? "No file linked" : `Unlinked: ${name}`;
				return { content: [{ type: "text" as const, text }] };
			}
			const filepath = params.filepath?.trim();
			if (!filepath) {
				return { content: [{ type: "text" as const, text: "md_log link requires filepath" }], isError: true };
			}
			const target = resolveLinkTarget(filepath, ctx.cwd);
			if (target.error) {
				return { content: [{ type: "text" as const, text: target.error }], isError: true };
			}
			const resolved = target.resolved!;
			if (logFile === resolved) {
				return { content: [{ type: "text" as const, text: `Already linked: ${resolved}` }] };
			}
			const written = linkFile(resolved, ctx);
			return {
				content: [
					{
						type: "text" as const,
						text: `Linked: ${resolved} (${written} entries backfilled). The session now mirrors to this file live.`,
					},
				],
			};
		},
	});

	// --- Backfill ---

	function backfill(ctx: any): number {
		if (!logFile) return 0;
		const entries: any[] = ctx.sessionManager.getEntries();
		if (entries.length === 0) return 0;

		const byId = new Map<string, any>();
		for (const e of entries) if (e.id) byId.set(e.id, e);

		// Active leaf = last entry that has an id (skip the session header).
		let leaf: any = null;
		for (let i = entries.length - 1; i >= 0; i--) {
			if (entries[i].id) {
				leaf = entries[i];
				break;
			}
		}
		if (!leaf) return 0;

		// Walk parent chain to root.
		const chain: any[] = [];
		let cur: any = leaf;
		const seen = new Set<string>();
		while (cur && cur.id && !seen.has(cur.id)) {
			seen.add(cur.id);
			chain.push(cur);
			cur = cur.parentId ? byId.get(cur.parentId) : null;
		}
		chain.reverse();

		// Track tool-call args from assistant messages so we can pair with results.
		const toolCallArgs = new Map<string, { name: string; args: any }>();

		const blocks: string[] = [];
		let count = 0;
		for (const entry of chain) {
			if (entry.type !== "message") continue;
			const msg = entry.message;
			if (!msg || !("role" in msg)) continue;
			count++;

			if (msg.role === "user") {
				const text = typeof msg.content === "string"
					? msg.content
					: Array.isArray(msg.content)
						? msg.content.filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n")
						: "";
				const trimmed = stripSkillBlocks(text.trim());
				if (trimmed) blocks.push(userBlock(trimmed));
				continue;
			}

			if (msg.role === "assistant") {
				// Index tool calls for later pairing.
				for (const c of msg.content || []) {
					if (c.type === "toolCall" && QA_TOOLS.has(c.name)) {
						toolCallArgs.set(c.id, { name: c.name, args: c.arguments });
					}
				}
				const textParts = (msg.content || [])
					.filter((c: any) => c.type === "text")
					.map((c: any) => (c.text as string).trim())
					.filter((t: string) => t.length > 0);
				if (textParts.length > 0) blocks.push(assistantBlock(textParts.join("\n\n")));
				continue;
			}

			if (msg.role === "toolResult") {
				if (!QA_TOOLS.has(msg.toolName)) continue;
				const tc = toolCallArgs.get(msg.toolCallId);
				// Question block. For quiz, use the persisted result's `details.options`
				// — the TRUE post-shuffle display order the user actually saw — rather
				// than the original tool-call args, which are the pre-shuffle author
				// order and can mismatch what's on screen. ask_user_question never
				// shuffles, so its tool-call args are already the true order.
				if (tc) {
					const a = tc.args || {};
					const label = tc.name === "quiz" ? "Quiz" : "Question";
					const shuffled = msg.toolName === "quiz"
						? (msg.details?.options as Array<{ index: number; label: string }> | undefined)
						: undefined;
					const options = shuffled && shuffled.length > 0
						? shuffled.map((o) => ({ label: o.label }))
						: (Array.isArray(a.options) ? a.options : []);
					blocks.push(questionCallout(label, a.question || "", a.details?.trim() || undefined, options));
				}
				if (msg.toolName === "quiz") {
					blocks.push(answerCalloutQuiz(msg.details));
				} else {
					blocks.push(answerCalloutAsk(msg.details));
				}
				continue;
			}
		}

		if (blocks.length > 0) {
			try {
				// Append rather than overwrite: the target note may already
				// contain content from a previous session/chapter. appendToFile
				// inserts a separator when the file is non-empty.
				appendToFile(blocks.join("\n\n"));
			} catch {
				// ignore
			}
		}
		return count;
	}
}
