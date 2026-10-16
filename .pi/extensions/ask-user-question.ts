import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	Editor,
	type EditorTheme,
	Key,
	Text,
	matchesKey,
	truncateToWidth,
	wrapTextWithAnsi,
} from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { LiveLines, LiveRegistry, hintLine, optionRow, renderEditorBlock } from "./lib/inline-question.ts";

interface AskOption {
	label: string;
	value: string;
	description?: string;
}

interface TextAnswer {
	type: "text";
	label: string;
	value: string;
}

interface OptionAnswer {
	type: "option";
	label: string;
	value: string;
	index: number;
}

interface OtherAnswer {
	type: "other";
	label: string;
	value: string;
}

type AskAnswer = TextAnswer | OptionAnswer | OtherAnswer;
type AskUserQuestionStatus = "answered" | "cancelled" | "unavailable";
type AskUserQuestionMode = "text" | "single-select" | "multi-select";

interface AskUserQuestionResultDetails {
	status: AskUserQuestionStatus;
	question: string;
	context?: string;
	mode: AskUserQuestionMode;
	answers: AskAnswer[];
	message?: string;
}

/**
 * 一次提问的活动状态。正文那一行（renderCall）和底部操作条（ctx.ui.custom）
 * 都读它，所以「选到第几项」「Other 打了什么字」只有这一份。
 * `version` 每变一次加一，正文那一行靠它自检重算（见 lib/inline-question.ts）。
 */
interface AskLive {
	toolCallId: string;
	question: string;
	context: string | undefined;
	options: AskOption[];
	multi: boolean;
	/** 显示行下标：单选 0..n-1＝选项、n＝Other；多选再多一行 Send。 */
	cursor: number;
	editing: boolean;
	otherText: string;
	selected: Map<string, AskAnswer>;
	version: number;
}

const askLive = new LiveRegistry<AskLive>();

function bump(live: AskLive): void {
	live.version += 1;
}

const OptionSchema = Type.Object({
	label: Type.String({
		description:
			'Display label for the option. If you recommend an option, place it first and append "(Recommended)" to the label.',
	}),
	value: Type.Optional(
		Type.String({
			description: "Optional machine-readable value returned for the option. Defaults to the label.",
		}),
	),
	description: Type.Optional(Type.String({ description: "Optional extra detail shown below the option." })),
});

const AskUserQuestionParams = Type.Object({
	question: Type.String({
		description: "The single question to ask the user. Ask exactly one question per tool call.",
	}),
	details: Type.Optional(
		Type.String({
			description: "Optional extra context or instructions shown under the question.",
		}),
	),
	options: Type.Optional(
		Type.Array(OptionSchema, {
			description:
				"Optional multiple-choice options. Omit or pass an empty array for free-form text input. Users will always be able to choose Other and type a custom answer when options are provided.",
		}),
	),
	multiSelect: Type.Optional(
		Type.Boolean({
			description: "Set to true to allow multiple answers to be selected for a question.",
		}),
	),
});

function normalizeOptions(options: Array<{ label: string; value?: string; description?: string }> | undefined): AskOption[] {
	return (options || [])
		.map((option) => ({
			label: option.label.trim(),
			value: option.value?.trim() || option.label.trim(),
			description: option.description?.trim() || undefined,
		}))
		.filter((option) => option.label.length > 0);
}

function getOtherLabel(options: AskOption[]): string {
	return options.some((option) => option.label.toLowerCase() === "other") ? "Other (custom)" : "Other";
}

function createEditorTheme(theme: any): EditorTheme {
	return {
		borderColor: (s) => theme.fg("accent", s),
		selectList: {
			selectedPrefix: (t) => theme.fg("accent", t),
			selectedText: (t) => theme.fg("accent", t),
			description: (t) => theme.fg("muted", t),
			scrollInfo: (t) => theme.fg("dim", t),
			noMatch: (t) => theme.fg("warning", t),
		},
	};
}

function addWrapped(lines: string[], text: string, width: number, indent = ""): void {
	const contentWidth = Math.max(1, width - indent.length);
	for (const line of wrapTextWithAnsi(text, contentWidth)) {
		lines.push(truncateToWidth(`${indent}${line}`, width));
	}
}

/**
 * 提问进行中的正文版：题干 + 选项（当前项 `> ` 高亮）+ Other（多选再加 Send）。
 * 只在「正文」里出现，底部条不重复画这些内容。
 */
function renderLivePanel(theme: any, width: number, live: AskLive): string[] {
	const lines: string[] = [];
	const add = (text: string) => lines.push(truncateToWidth(text, width));
	const otherLabel = getOtherLabel(live.options);
	const otherIndex = live.options.length;

	add(theme.fg("toolTitle", theme.bold("ask_user_question ")) + theme.fg("text", live.question));
	if (live.context) {
		addWrapped(lines, theme.fg("muted", live.context), width, "  ");
	}

	for (let i = 0; i < live.options.length; i++) {
		const option = live.options[i];
		const marker = live.multi ? `${live.selected.has(`option:${i}`) ? "[x]" : "[ ]"} ${i + 1}. ` : `${i + 1}. `;
		add(optionRow(theme, live.cursor === i, `${marker}${option.label}`, option.description));
	}

	const otherText = live.otherText.trim();
	if (live.multi) {
		const marker = live.selected.has("other") ? "[x]" : "[ ]";
		add(
			optionRow(
				theme,
				live.cursor === otherIndex,
				`${marker} ${otherLabel}`,
				otherText.length > 0 ? `— ${live.otherText}` : undefined,
			),
		);
		const submitLabel = live.selected.size > 0 ? `✓ Send (${live.selected.size} selected)` : "○ Send";
		add(optionRow(theme, live.cursor === otherIndex + 1, submitLabel));
	} else {
		add(optionRow(theme, live.cursor === otherIndex, otherLabel, otherText.length > 0 ? `— ${live.otherText}` : undefined));
	}

	return lines;
}

/**
 * 问答结束后的正文版：就是原来的那条静态行（标题 + Options 一览）。
 * 答案本身由 renderResult 画在下面，所以这里不重复。
 */
function renderStaticPanel(theme: any, width: number, args: any): string[] {
	const lines: string[] = [];
	let head = theme.fg("toolTitle", theme.bold("ask_user_question ")) + theme.fg("muted", args.question);
	if (args.multiSelect) {
		head += theme.fg("dim", " [multi-select]");
	}
	addWrapped(lines, head, width);

	// 这个函数现在是在「组件 render()」里跑的（renderCall 的返回值），抛异常会直接
	// 冒到 TUI 渲染循环里 —— 参数还在流式或不合法时只画标题就好。
	try {
		const options = normalizeOptions(
			args.options as Array<{ label: string; value?: string; description?: string }> | undefined,
		);
		if (options.length > 0) {
			const labels = [...options.map((option) => option.label), getOtherLabel(options)].join(", ");
			addWrapped(lines, theme.fg("dim", `Options: ${labels}`), width, "  ");
		}
	} catch {
		/* 流式参数/不合法参数：忽略选项一览 */
	}
	return lines;
}

function formatAnswerForModel(answer: AskAnswer): string {
	switch (answer.type) {
		case "text":
			return answer.label;
		case "other":
			return `Other: ${answer.label}`;
		case "option":
			return `${answer.index}. ${answer.label}`;
	}
}

function answerSortRank(answer: AskAnswer): number {
	switch (answer.type) {
		case "option":
			return answer.index;
		case "other":
			return Number.MAX_SAFE_INTEGER - 1;
		case "text":
			return Number.MAX_SAFE_INTEGER;
	}
}

function sortAnswers(answers: AskAnswer[]): AskAnswer[] {
	return [...answers].sort((a, b) => answerSortRank(a) - answerSortRank(b));
}

function buildStructuredResult(
	status: AskUserQuestionStatus,
	question: string,
	mode: AskUserQuestionMode,
	answers: AskAnswer[],
	context?: string,
	message?: string,
) {
	return {
		status,
		question,
		context,
		mode,
		answers,
		message,
	} as AskUserQuestionResultDetails;
}

function cancelledResult(question: string, mode: AskUserQuestionMode, context?: string) {
	const message = "User cancelled the question";
	return {
		content: [{ type: "text" as const, text: message }],
		details: buildStructuredResult("cancelled", question, mode, [], context, message),
	};
}

function unavailableResult(question: string, mode: AskUserQuestionMode, message: string, context?: string) {
	return {
		content: [{ type: "text" as const, text: message }],
		details: buildStructuredResult("unavailable", question, mode, [], context, message),
	};
}

function buildResult(question: string, context: string | undefined, mode: AskUserQuestionMode, answers: AskAnswer[]) {
	let text: string;
	if (mode === "text") {
		const answer = answers[0];
		text = answer.label.trim().length > 0 ? `User answered: ${answer.label}` : "User submitted an empty response";
	} else if (mode === "single-select") {
		text = `User selected: ${formatAnswerForModel(answers[0])}`;
	} else {
		text = `User selected:\n${answers.map((answer) => `- ${formatAnswerForModel(answer)}`).join("\n")}`;
	}

	return {
		content: [{ type: "text" as const, text }],
		details: buildStructuredResult("answered", question, mode, answers, context),
	};
}

/**
 * 单选：键盘在底部那一行，选项画在正文里（见 renderLivePanel）。
 */
async function askSingleChoice(ctx: any, live: AskLive): Promise<AskAnswer | null> {
	const options = live.options;
	const total = options.length + 1; // + Other
	const otherIndex = options.length;

	return ctx.ui.custom<AskAnswer | null>((tui: any, theme: any, _kb: any, done: (result: AskAnswer | null) => void) => {
		let cachedLines: string[] | undefined;
		let cachedWidth = -1;
		const editor = new Editor(tui, createEditorTheme(theme));

		editor.onSubmit = (value) => {
			const trimmed = value.trim();
			if (!trimmed) return;
			live.otherText = trimmed;
			done({ type: "other", label: trimmed, value: trimmed });
		};

		function refresh() {
			cachedLines = undefined;
			bump(live);
			tui.requestRender();
		}

		function handleInput(data: string) {
			if (live.editing) {
				if (matchesKey(data, Key.escape)) {
					live.editing = false;
					live.otherText = "";
					editor.setText("");
					refresh();
					return;
				}
				editor.handleInput(data);
				live.otherText = editor.getText();
				refresh();
				return;
			}

			if (matchesKey(data, Key.up)) {
				live.cursor = Math.max(0, live.cursor - 1);
				refresh();
				return;
			}
			if (matchesKey(data, Key.down)) {
				live.cursor = Math.min(total - 1, live.cursor + 1);
				refresh();
				return;
			}
			if (matchesKey(data, Key.enter)) {
				if (live.cursor === otherIndex) {
					live.editing = true;
					live.otherText = "";
					editor.setText("");
					refresh();
					return;
				}
				const option = options[live.cursor];
				done({
					type: "option",
					label: option.label,
					value: option.value,
					index: live.cursor + 1,
				});
				return;
			}
			if (matchesKey(data, Key.escape)) {
				done(null);
			}
		}

		function render(width: number): string[] {
			// 缓存按 width 记：pi-tui 在 resize 时只 requestRender、不 invalidate，
			// render 会用新 width 重入，返回宽度不符的旧行会崩进程。
			if (cachedLines && cachedWidth === width) return cachedLines;

			const lines: string[] = [];
			if (live.editing) {
				// 要打字时才展开成输入框（编辑器自带边框与光标），平时底部只有一行提示。
				lines.push(...renderEditorBlock(theme, width, "自定义回答：", editor));
				lines.push(hintLine(theme, width, "Enter 提交 · Esc 返回"));
			} else {
				lines.push(hintLine(theme, width, "↑↓ 选择 · Enter 确认 · Esc 取消"));
			}

			// 编辑态不缓存：编辑器画的是活光标。
			if (live.editing) {
				cachedLines = undefined;
				cachedWidth = -1;
			} else {
				cachedLines = lines;
				cachedWidth = width;
			}
			return lines;
		}

		return {
			render,
			invalidate: () => {
				cachedLines = undefined;
				editor.invalidate();
			},
			handleInput,
		};
	});
}

/**
 * 多选：同上，另加 Send 行与勾选标记。
 */
async function askMultiChoice(ctx: any, live: AskLive): Promise<AskAnswer[] | null> {
	const options = live.options;
	const otherIndex = options.length;
	const submitIndex = options.length + 1;
	const otherLabel = getOtherLabel(options);

	return ctx.ui.custom<AskAnswer[] | null>(
		(tui: any, theme: any, _kb: any, done: (result: AskAnswer[] | null) => void) => {
			let cachedLines: string[] | undefined;
			let cachedWidth = -1;
			const editor = new Editor(tui, createEditorTheme(theme));

			editor.onSubmit = (value) => {
				const trimmed = value.trim();
				if (!trimmed) return;
				live.selected.set("other", { type: "other", label: trimmed, value: trimmed });
				live.otherText = trimmed;
				live.editing = false;
				refresh();
			};

			function refresh() {
				cachedLines = undefined;
				bump(live);
				tui.requestRender();
			}

			function toggleOption(index: number) {
				const key = `option:${index}`;
				if (live.selected.has(key)) {
					live.selected.delete(key);
				} else {
					const option = options[index];
					live.selected.set(key, {
						type: "option",
						label: option.label,
						value: option.value,
						index: index + 1,
					});
				}
				refresh();
			}

			function handleInput(data: string) {
				if (live.editing) {
					if (matchesKey(data, Key.escape)) {
						live.editing = false;
						live.otherText = live.selected.get("other")?.label || "";
						editor.setText(live.otherText);
						refresh();
						return;
					}
					editor.handleInput(data);
					live.otherText = editor.getText();
					refresh();
					return;
				}

				if (matchesKey(data, Key.up)) {
					live.cursor = Math.max(0, live.cursor - 1);
					refresh();
					return;
				}
				if (matchesKey(data, Key.down)) {
					live.cursor = Math.min(submitIndex, live.cursor + 1);
					refresh();
					return;
				}

				if (matchesKey(data, Key.enter)) {
					if (live.cursor === submitIndex) {
						if (live.selected.size > 0) {
							done(sortAnswers(Array.from(live.selected.values())));
						}
						return;
					}
					if (live.cursor === otherIndex) {
						live.editing = true;
						live.otherText = live.selected.get("other")?.label || "";
						editor.setText(live.otherText);
						refresh();
						return;
					}
					toggleOption(live.cursor);
					return;
				}

				if (matchesKey(data, Key.escape)) {
					done(null);
				}
			}

			function render(width: number): string[] {
				if (cachedLines && cachedWidth === width) return cachedLines;

				const lines: string[] = [];
				if (live.editing) {
					lines.push(...renderEditorBlock(theme, width, `${otherLabel}：`, editor));
					lines.push(hintLine(theme, width, "Enter 保存 · Esc 返回"));
				} else {
					if (live.selected.size === 0) {
						lines.push(truncateToWidth(theme.fg("warning", " 至少选一项再 Send"), width));
					}
					lines.push(hintLine(theme, width, "↑↓ 移动 · Enter 勾选 · Send 提交 · Esc 取消"));
				}

				if (live.editing) {
					cachedLines = undefined;
					cachedWidth = -1;
				} else {
					cachedLines = lines;
					cachedWidth = width;
				}
				return lines;
			}

			return {
				render,
				invalidate: () => {
					cachedLines = undefined;
					editor.invalidate();
				},
				handleInput,
			};
		},
	);
}

// Shared UI mutex. ctx.ui.custom()/editor can only handle one active call at
// a time, so ALL pop-up-style tools (ask_user_question, quiz, ...) must
// serialize against each other, not just against themselves. We stash one
// mutex on globalThis so separate extension files can share it without
// importing each other.
const SHARED_UI_LOCK_KEY = "__piSharedUiLock";
function getSharedUiLock() {
	const g = globalThis as any;
	if (!g[SHARED_UI_LOCK_KEY]) {
		let chain: Promise<void> = Promise.resolve();
		g[SHARED_UI_LOCK_KEY] = {
			withLock<T>(fn: () => T | Promise<T>): Promise<T> {
				const prev = chain;
				let release: () => void;
				chain = new Promise<void>((r) => { release = r; });
				return prev.then(fn).finally(() => release!());
			},
		};
	}
	return g[SHARED_UI_LOCK_KEY] as { withLock<T>(fn: () => Promise<T>): Promise<T> };
}
const sharedUiLock = getSharedUiLock();

function withUILock<T>(fn: () => Promise<T>): Promise<T> {
	return sharedUiLock.withLock(fn);
}

export default function askUserQuestion(pi: ExtensionAPI) {
	pi.registerTool({
		name: "ask_user_question",
		label: "ask_user_question",
		description:
			"Ask the user a single question and pause execution until they answer. Use this when requirements are ambiguous, user preferences are needed, a decision would materially affect implementation, or you need confirmation before proceeding. Ask exactly one question per tool call, and prefer multiple separate tool calls over bundling unrelated questions together.",
		promptSnippet:
			"Use this tool to ask exactly one clarifying question, missing-requirement question, preference question, or decision question before continuing.",
		promptGuidelines: [
			"Ask exactly one question per tool call.",
			"If you need answers to multiple questions, make multiple separate ask_user_question tool calls instead of combining them into one prompt.",
			'Users will always be able to select "Other" to provide custom text input when options are provided.',
			"Use multiSelect: true only when you need multiple answers to the same question.",
			'If you recommend a specific option, make it the first option in the list and add "(Recommended)" at the end of the label.',
			"Prefer this tool over guessing when requirements, preferences, or implementation choices are unclear.",
			"Use this tool when multiple valid implementation paths exist and the preferred path depends on user choice.",
		],
		parameters: AskUserQuestionParams,

		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			const options = normalizeOptions(params.options);
			const context = params.details?.trim() || undefined;
			const mode: AskUserQuestionMode = options.length === 0 ? "text" : params.multiSelect ? "multi-select" : "single-select";

			if (signal?.aborted) {
				return cancelledResult(params.question, mode, context);
			}

			if (!ctx.hasUI) {
				return unavailableResult(params.question, mode, "ask_user_question requires interactive mode UI", context);
			}

			if (mode === "text") {
				return withUILock(async () => {
					const editorTitle = context ? `${params.question}\n\n${context}` : params.question;
					const answer = await ctx.ui.editor(editorTitle);
					if (answer === undefined) {
						return cancelledResult(params.question, mode, context);
					}
					return buildResult(params.question, context, mode, [
						{ type: "text", label: answer.trim(), value: answer.trim() },
					]);
				});
			}

			const live: AskLive = {
				toolCallId,
				question: params.question,
				context,
				options,
				multi: mode === "multi-select",
				cursor: 0,
				editing: false,
				otherText: "",
				selected: new Map(),
				version: 0,
			};
			askLive.set(toolCallId, live);

			try {
				return await withUILock(async () => {
					const answers = live.multi
						? await askMultiChoice(ctx, live)
						: await askSingleChoice(ctx, live);
					if (!answers) {
						return cancelledResult(params.question, mode, context);
					}
					return buildResult(params.question, context, mode, Array.isArray(answers) ? answers : [answers]);
				});
			} finally {
				// 正文那一行随即回落到静态版（答案由 renderResult 画在下面）。
				askLive.delete(toolCallId);
			}
		},

		renderCall(args, theme, context) {
			// 题目画在会话正文里：pi 把工具调用的 call 组件与 result 组件并排画在同一行，
			// 工具结束后 call 组件仍然保留，所以题目会留在会话末尾、跟着消息一起滚动。
			// 提问进行中画交互版（光标/勾选），结束后回落到静态版（答案在下面那行）。
			const id = context.toolCallId;
			const current = () => askLive.get(id);
			return new LiveLines(
				() => {
					const live = current();
					return live ? `live:${live.version}` : "static";
				},
				(width) => {
					const live = current();
					return live ? renderLivePanel(theme, width, live) : renderStaticPanel(theme, width, args);
				},
			);
		},

		renderResult(result, _options, theme) {
			const details = result.details as AskUserQuestionResultDetails | undefined;
			if (!details) {
				const first = result.content[0];
				return new Text(first?.type === "text" ? first.text : "", 0, 0);
			}

			if (details.status === "cancelled") {
				return new Text(theme.fg("warning", details.message || "Cancelled"), 0, 0);
			}

			if (details.status === "unavailable") {
				return new Text(theme.fg("warning", details.message || "ask_user_question unavailable"), 0, 0);
			}

			const lines = details.answers.map((answer) => {
				switch (answer.type) {
					case "text":
						return `${theme.fg("success", "✓ ")}${theme.fg("accent", answer.label || "(empty response)")}`;
					case "other":
						return `${theme.fg("success", "✓ ")}${theme.fg("muted", "Other: ")}${theme.fg("accent", answer.label)}`;
					case "option":
						return `${theme.fg("success", "✓ ")}${theme.fg("accent", `${answer.index}. ${answer.label}`)}`;
				}
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
