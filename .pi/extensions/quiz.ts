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

// ────────────────────────────────────────────────────────────────────────────
// quiz — a GRADED sibling of ask_user_question.
//
// Where ask_user_question collects a preference/decision with no notion of
// right or wrong, `quiz` poses a question that HAS a correct answer, grades the
// user's selection instantly, and shows tight feedback (✓/✗ + the correct
// answer + an optional explanation) to both the user and the agent.
//
// It is intentionally options-only: single-select or multi-select. There is no
// free-text mode and no "Other" option, because a free-text answer can't be
// graded against a correct index.
// ────────────────────────────────────────────────────────────────────────────

interface QuizOption {
	label: string;
	value: string;
	description?: string;
}

interface OptionAnswer {
	label: string;
	value: string;
	index: number; // 1-based, matches the number shown to the user
}

// The always-present "I don't know" choice. It is NOT a real option: it never
// participates in shuffling, has no correct-answer value, and produces a
// distinct signal (dontKnow) rather than a right/wrong grade — so an honest
// "I don't know" is never confused with a lucky or unlucky guess.
const DONT_KNOW_VALUE = "__dont_know__";
const DONT_KNOW_LABEL = "I don't know";
const DONT_KNOW_INDEX = 0; // real options are 1-based; submit uses -1

// Unified response from either ask* component. answers holds the real
// selections (empty when dontKnow); note is the optional free-text the user
// typed in the always-present note field (kept only when non-empty).
interface QuizResponse {
	dontKnow: boolean;
	note?: string;
	answers: OptionAnswer[];
}

type QuizStatus = "answered" | "cancelled" | "unavailable";
type QuizMode = "single-select" | "multi-select";

interface DisplayedOption {
	index: number; // 1-based, in the final (possibly shuffled) display order
	label: string;
}

interface QuizResultDetails {
	status: QuizStatus;
	question: string;
	context?: string;
	mode: QuizMode;
	answers: OptionAnswer[];
	correctIndices: number[];
	options?: DisplayedOption[]; // full option list in display order, for the transcript
	correct?: boolean;
	dontKnow?: boolean; // user selected "I don't know" instead of guessing
	note?: string; // optional free-text from the always-present note field (any answer)
	explanation?: string;
	message?: string;
}

const OptionSchema = Type.Object({
	label: Type.String({ description: "Display label for the answer option." }),
	value: Type.Optional(
		Type.String({ description: "Optional machine-readable value returned for the option. Defaults to the label." }),
	),
	description: Type.Optional(Type.String({ description: "Optional extra detail shown below the option." })),
});

const QuizParams = Type.Object({
	question: Type.String({
		description: "The single quiz question to ask. Ask exactly one question per tool call.",
	}),
	details: Type.Optional(
		Type.String({ description: "Optional extra context or instructions shown under the question." }),
	),
	options: Type.Array(OptionSchema, {
		description:
			"The answer options (2 or more). Options only — there is no free-text mode. Give each option a stable `value`; you reference the correct one by that value in correctAnswer.",
		minItems: 2,
	}),
	multiSelect: Type.Optional(
		Type.Boolean({ description: "Set to true when more than one option is correct and the user must select all of them." }),
	),
	correctAnswer: Type.Union([Type.String(), Type.Array(Type.String())], {
		description:
			'REQUIRED. The correct answer as the option value(s) — the `value` field of the option you intend. Single-select: a single string (e.g. "mercury"). Multi-select: an array of strings (e.g. ["belize", "niue"]); the user is only correct if their selection matches this set exactly. Always pass the value, not a position number — this is self-checking and prevents miscounting.',
	}),
	explanation: Type.String({
		description:
			"REQUIRED. Explanation revealed AFTER the user answers (shown whether they got it right or wrong). Use it to reinforce why the correct answer is correct.",
	}),
	shuffle: Type.Optional(
		Type.Boolean({
			description:
				"Defaults to true: options are randomly reordered before display so the correct answer isn't always in the same position. Set to false only when option order is meaningful (e.g. ordered numeric values, or an 'All/None of the above' option that must stay last).",
		}),
	),
});

// The model routinely emits `explanation` with literal "\n" sequences — i.e.
// double-escaped inside the JSON string — so after decoding they remain two
// characters (backslash + n) instead of a real line break. That collapses a
// multi-paragraph explanation into one run-on block, both in the TUI feedback
// and in the md-log note, defeating the "one option per paragraph" rule.
// Restore them to real newlines once, here at the entry point, so every
// downstream consumer (feedback render, transcript, md-log) gets clean text.
// Only the two-character sequence is touched; single backslashes are left
// alone, so legitimate escapes in the prose survive.
function normalizeEscapedNewlines(text: string): string {
	return text.replace(/\\n/g, "\n");
}

function normalizeOptions(
	options: Array<{ label: string; value?: string; description?: string }> | undefined,
): QuizOption[] {
	const seen = new Set<string>();
	return (options || [])
		.map((option) => ({
			label: option.label.trim(),
			value: option.value?.trim() || option.label.trim(),
			description: option.description?.trim() || undefined,
		}))
		.filter((option) => {
			if (option.label.length === 0) return false;
			if (seen.has(option.value)) throw new Error(`duplicate option value "${option.value}"`);
			seen.add(option.value);
			return true;
		});
}

// Fisher-Yates shuffle over a copy. Safe to reorder for display because
// correctAnswer is keyed by value, not position — indices are resolved AFTER
// shuffling, so grading always matches what the user actually sees.
function shuffleOptions(options: QuizOption[]): QuizOption[] {
	const out = [...options];
	for (let i = out.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[out[i], out[j]] = [out[j], out[i]];
	}
	return out;
}

// Resolve author-supplied option value(s) to 1-based indices. Keying by value
// (not position) makes the correct answer self-documenting: the author writes
// `correctAnswer: "mercury"` and a typo becomes a hard error instead of a
// silent wrong grade.
// The harness sometimes delivers a multi-select `correctAnswer` array as a
// JSON-stringified string (e.g. '["a", "b"]') instead of a real array, because
// the schema union lists String first. Detect that case and parse it back into
// an array so grading resolves against real option values. A plain single value
// is wrapped as-is.
function coerceCorrectAnswer(correctAnswer: string | string[]): string[] {
	if (Array.isArray(correctAnswer)) return correctAnswer;
	const trimmed = correctAnswer.trim();
	if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
		try {
			const parsed = JSON.parse(trimmed);
			if (Array.isArray(parsed)) return parsed.map((v) => String(v));
		} catch {
			// Not valid JSON — fall through and treat as a single literal value.
		}
	}
	return [correctAnswer];
}

function resolveCorrect(
	correctAnswer: string | string[] | undefined,
	options: QuizOption[],
): { indices: number[]; error?: string } {
	if (correctAnswer === undefined) return { indices: [], error: "correctAnswer is required" };
	const arr = coerceCorrectAnswer(correctAnswer);
	if (arr.length === 0) return { indices: [], error: "correctAnswer is required" };
	const byValue = new Map(options.map((o, i) => [o.value, i + 1]));
	const indices: number[] = [];
	for (const raw of arr) {
		const v = typeof raw === "string" ? raw.trim() : raw;
		const idx = byValue.get(v);
		if (idx === undefined) {
			const known = options.map((o) => `"${o.value}"`).join(", ");
			return { indices: [], error: `correctAnswer "${v}" does not match any option value (${known})` };
		}
		indices.push(idx);
	}
	return { indices: Array.from(new Set(indices)).sort((a, b) => a - b) };
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

function isCorrect(selectedIndices: number[], correctIndices: number[]): boolean {
	if (selectedIndices.length !== correctIndices.length) return false;
	const a = [...selectedIndices].sort((x, y) => x - y);
	const b = [...correctIndices].sort((x, y) => x - y);
	return a.every((v, i) => v === b[i]);
}

function buildStructuredResult(
	status: QuizStatus,
	question: string,
	mode: QuizMode,
	answers: OptionAnswer[],
	correctIndices: number[],
	correct: boolean | undefined,
	explanation: string | undefined,
	context?: string,
	message?: string,
	options?: DisplayedOption[],
	dontKnow?: boolean,
	note?: string,
): QuizResultDetails {
	return { status, question, context, mode, answers, correctIndices, options, correct, dontKnow, note, explanation, message };
}

function cancelledResult(question: string, mode: QuizMode, correctIndices: number[], context?: string) {
	const message = "User cancelled the quiz";
	return {
		content: [{ type: "text" as const, text: message }],
		details: buildStructuredResult("cancelled", question, mode, [], correctIndices, undefined, undefined, context, message),
	};
}

function unavailableResult(question: string, mode: QuizMode, message: string, correctIndices: number[], context?: string) {
	return {
		content: [{ type: "text" as const, text: message }],
		details: buildStructuredResult("unavailable", question, mode, [], correctIndices, undefined, undefined, context, message),
	};
}

function formatOptionRef(options: QuizOption[], index: number): string {
	const opt = options.find((o, i) => i + 1 === index);
	return `${index}. ${opt ? opt.label : "(unknown)"}`;
}

function buildResult(
	question: string,
	context: string | undefined,
	mode: QuizMode,
	options: QuizOption[],
	response: QuizResponse,
	correctIndices: number[],
	explanation: string | undefined,
) {
	const { dontKnow, note, answers } = response;
	const selectedIndices = answers.map((a) => a.index);
	// "I don't know" is never counted as correct — it's a distinct outcome.
	const correct = dontKnow ? false : isCorrect(selectedIndices, correctIndices);
	const correctStr = correctIndices.map((i) => formatOptionRef(options, i)).join(", ");
	const displayedOptions: DisplayedOption[] = options.map((o, i) => ({ index: i + 1, label: o.label }));

	let text: string;
	if (dontKnow) {
		// Make the signal explicit for the agent: the user did NOT guess, so this
		// is a genuine knowledge gap, not a wrong answer to correct against.
		text = `User selected "I don't know" — they did not attempt an answer (a genuine knowledge gap, not a wrong guess).`;
		text += `\nCorrect: ${correctStr}`;
		if (note) text += `\nUser's note: ${note}`;
	} else {
		const verdict = correct ? "correctly" : "incorrectly";
		const selectedStr = answers.map((a) => `${a.index}. ${a.label}`).join(", ");
		text = `User answered ${verdict}.\nSelected: ${selectedStr}\nCorrect: ${correctStr}`;
		if (note) text += `\nUser's note: ${note}`;
	}
	if (explanation) text += `\nExplanation: ${explanation}`;

	return {
		content: [{ type: "text" as const, text }],
		details: buildStructuredResult(
			"answered",
			question,
			mode,
			answers,
			correctIndices,
			correct,
			explanation,
			context,
			undefined,
			displayedOptions,
			dontKnow,
			note,
		),
	};
}

// Shared feedback block, rendered after the user submits.
function renderFeedback(
	lines: string[],
	theme: any,
	width: number,
	options: QuizOption[],
	selectedIndices: number[],
	correctIndices: number[],
	explanation: string | undefined,
	dontKnow = false,
	note?: string,
): void {
	const add = (text: string) => lines.push(truncateToWidth(text, width));
	const correct = !dontKnow && isCorrect(selectedIndices, correctIndices);
	const selectedSet = new Set(selectedIndices);
	const correctSet = new Set(correctIndices);

	lines.push("");
	for (let i = 0; i < options.length; i++) {
		const index = i + 1;
		const opt = options[i];
		const isSelected = selectedSet.has(index);
		const isKey = correctSet.has(index);
		let marker: string;
		let color: string;
		if (dontKnow) {
			// No guess was made — only reveal the correct answer(s); never show ✗.
			marker = isKey ? "✓" : " ";
			color = isKey ? "success" : "dim";
		} else if (isSelected && isKey) {
			marker = "✓";
			color = "success";
		} else if (isSelected && !isKey) {
			marker = "✗";
			color = "error";
		} else if (!isSelected && isKey) {
			// correct answer the user missed
			marker = "✓";
			color = "success";
		} else {
			marker = " ";
			color = "dim";
		}
		add(theme.fg(color, ` ${marker} ${index}. ${opt.label}`));
	}

	lines.push("");
	if (dontKnow) {
		add(theme.fg("warning", " · You said: I don't know"));
		const correctStr = correctIndices.map((i) => formatOptionRef(options, i)).join(", ");
		addWrapped(lines, theme.fg("muted", `Correct answer: ${correctStr}`), width, " ");
	} else if (correct) {
		add(theme.fg("success", " ✓ Correct!"));
	} else {
		add(theme.fg("error", " ✗ Incorrect."));
		const correctStr = correctIndices.map((i) => formatOptionRef(options, i)).join(", ");
		addWrapped(lines, theme.fg("muted", `Correct answer: ${correctStr}`), width, " ");
	}
	if (note) {
		addWrapped(lines, theme.fg("muted", `Your note: ${note}`), width, " ");
	}
	if (explanation) {
		lines.push("");
		addWrapped(lines, theme.fg("text", explanation), width, " ");
	}
	// The hint line and the note input live in the bottom bar now (see
	// renderQuizLive / the ask* components), so this only draws the feedback body.
}

// ────────────────────────────────────────────────────────────────────────────
// 题目画在会话正文里（renderCall），屏幕底部只留一行操作条（ctx.ui.custom）。
// 两边都要读同一份状态，所以放 QuizLive；正文那一行靠 version 自检重算。
// ────────────────────────────────────────────────────────────────────────────

const DONT_KNOW_KEY = "dont-know"; // 多选的 selected map 里代表「I don't know」

interface QuizLive {
	toolCallId: string;
	question: string;
	context: string | undefined;
	options: QuizOption[]; // 已 shuffle 的显示顺序
	correctIndices: number[];
	explanation: string | undefined;
	multi: boolean;
	/** 显示行下标：0..n-1＝选项、n＝I don't know；多选再加一行 Send。 */
	cursor: number;
	phase: "select" | "feedback";
	focus: "options" | "note";
	chosen: OptionAnswer | null; // 单选选中项
	dontKnow: boolean; // 单选选了「I don't know」
	selected: Map<string, OptionAnswer>; // 多选（键含 DONT_KNOW_KEY）
	note: string; // 笔记编辑器内容的镜像，供正文那一行显示
	version: number;
}

const quizLive = new LiveRegistry<QuizLive>();

function bumpQuiz(live: QuizLive): void {
	live.version += 1;
}

function noteOf(live: QuizLive): string | undefined {
	const t = live.note.trim();
	return t.length ? t : undefined;
}

function liveRealAnswers(live: QuizLive): OptionAnswer[] {
	return sortAnswers(Array.from(live.selected.values()).filter((a) => a.index !== DONT_KNOW_INDEX));
}

function liveDontKnow(live: QuizLive): boolean {
	return live.multi ? live.selected.has(DONT_KNOW_KEY) : live.dontKnow;
}

/**
 * 提问进行中的正文版：
 *   select   ：题干 + 选项（当前项 `> ` 高亮）+ I don't know（+ 多选的 Send）
 *   feedback ：renderFeedback 的 ✓/✗ + 判定 + 正确项 + 解析
 * 笔记只画一行镜像，真正的输入框在底部条里。
 */
function renderQuizLive(theme: any, width: number, live: QuizLive): string[] {
	const lines: string[] = [];
	const add = (text: string) => lines.push(truncateToWidth(text, width));
	const optionsFocused = live.focus === "options";

	add(theme.fg("toolTitle", theme.bold("quiz ")) + theme.fg("text", live.question));
	if (live.context) {
		addWrapped(lines, theme.fg("muted", live.context), width, "  ");
	}

	if (live.phase === "feedback") {
		renderFeedback(
			lines,
			theme,
			width,
			live.options,
			live.multi ? liveRealAnswers(live).map((a) => a.index) : live.chosen ? [live.chosen.index] : [],
			live.correctIndices,
			live.explanation,
			liveDontKnow(live),
			noteOf(live),
		);
		return lines;
	}

	for (let i = 0; i < live.options.length; i++) {
		const option = live.options[i];
		const marker = live.multi
			? `${live.selected.has(`option:${i}`) ? "[x]" : "[ ]"} ${i + 1}. `
			: `${i + 1}. `;
		add(optionRow(theme, optionsFocused && live.cursor === i, `${marker}${option.label}`, option.description));
	}

	// I don't know：刻意压暗，读起来与可判分的选项分开。
	const checked = liveDontKnow(live);
	const dontKnowFocused = optionsFocused && live.cursor === live.options.length;
	const dontKnowLabel = live.multi ? `${checked ? "[x]" : "[ ]"} ${DONT_KNOW_LABEL}` : DONT_KNOW_LABEL;
	const dontKnowPrefix = dontKnowFocused ? theme.fg("accent", "> ") : "  ";
	const dontKnowStyled = dontKnowFocused
		? theme.fg("accent", dontKnowLabel)
		: theme.fg(checked ? "warning" : "dim", dontKnowLabel);
	add(`${dontKnowPrefix}${dontKnowStyled}`);

	if (live.multi) {
		const submitLabel = live.selected.size > 0 ? `✓ Send (${live.selected.size} selected)` : "○ Send";
		add(optionRow(theme, optionsFocused && live.cursor === live.options.length + 1, submitLabel));
	}

	if (live.note.trim().length > 0) {
		addWrapped(lines, theme.fg("muted", `Note: ${live.note}`), width, "  ");
	}
	return lines;
}

/**
 * 问答结束后的正文版：就是原来的单行标题。
 * 题目/选项/✓✗/解析由 renderResult 完整复述，所以这里不要重复画。
 */
function renderQuizStatic(theme: any, width: number, args: any): string[] {
	let text = theme.fg("toolTitle", theme.bold("quiz ")) + theme.fg("muted", args.question);
	if (args.multiSelect) {
		text += theme.fg("dim", " [multi-select]");
	}
	try {
		const options = normalizeOptions(args.options as Array<{ label: string; value?: string; description?: string }> | undefined);
		if (options.length > 0) {
			const noun = options.length === 1 ? "option" : "options";
			text += theme.fg("dim", ` (${options.length} ${noun})`);
		}
	} catch {
		// 参数还在流式、或本身不合法：只画标题就好
	}
	const lines: string[] = [];
	addWrapped(lines, text, width);
	return lines;
}

// Build the note Editor. `disableSubmit` is set because Enter must NOT submit
// here: the editor's submit path clears the buffer, which would wipe the note.
// Instead the host intercepts Enter to return focus to the options while
// keeping the text. Ctrl+J still inserts a newline (pi convention), so
// multi-line notes work.
function makeNoteEditor(tui: any, theme: any): Editor {
	const editor = new Editor(tui, createEditorTheme(theme));
	editor.focused = false;
	editor.disableSubmit = true;
	return editor;
}

async function askSingleChoice(ctx: any, live: QuizLive): Promise<QuizResponse | null> {
	const options = live.options;
	const dontKnowNav = options.length; // nav index of the "I don't know" row

	return ctx.ui.custom<QuizResponse | null>(
		(tui: any, theme: any, _kb: any, done: (result: QuizResponse | null) => void) => {
			const editor = makeNoteEditor(tui, theme);
			let cachedLines: string[] | undefined;
			let cachedWidth = -1;

			function refresh() {
				cachedLines = undefined;
				bumpQuiz(live);
				tui.requestRender();
			}

			function toOptions() {
				live.focus = "options";
				editor.focused = false;
				refresh();
			}

			function response(): QuizResponse {
				const note = noteOf(live);
				return live.dontKnow
					? { dontKnow: true, note, answers: [] }
					: { dontKnow: false, note, answers: live.chosen ? [live.chosen] : [] };
			}

			function handleInput(data: string) {
				if (live.phase === "feedback") {
					// Tab toggles focus between the static result view and the note
					// field: the user may want to comment on the explanation itself.
					if (matchesKey(data, Key.tab)) {
						live.focus = live.focus === "options" ? "note" : "options";
						editor.focused = live.focus === "note";
						refresh();
						return;
					}
					if (live.focus === "note") {
						if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
							toOptions();
							return;
						}
						editor.handleInput(data);
						live.note = editor.getText();
						refresh();
						return;
					}
					if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
						done(response());
					}
					return;
				}

				// Tab toggles focus between the options list and the note field.
				if (matchesKey(data, Key.tab)) {
					live.focus = live.focus === "options" ? "note" : "options";
					editor.focused = live.focus === "note";
					refresh();
					return;
				}

				if (live.focus === "note") {
					// Enter and Esc both return to the options and keep the note text.
					// (Enter must be intercepted here: the editor's own submit clears
					// the buffer. Ctrl+J still reaches the editor as a newline.)
					if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
						toOptions();
						return;
					}
					editor.handleInput(data);
					live.note = editor.getText();
					refresh();
					return;
				}

				// focus === "options"
				if (matchesKey(data, Key.up)) {
					live.cursor = Math.max(0, live.cursor - 1);
					refresh();
					return;
				}
				if (matchesKey(data, Key.down)) {
					live.cursor = Math.min(dontKnowNav, live.cursor + 1);
					refresh();
					return;
				}
				if (matchesKey(data, Key.enter)) {
					if (live.cursor === dontKnowNav) {
						live.dontKnow = true;
						live.chosen = null;
					} else {
						const selected = options[live.cursor];
						live.chosen = { label: selected.label, value: selected.value, index: live.cursor + 1 };
						live.dontKnow = false;
					}
					live.phase = "feedback";
					refresh();
					return;
				}
				if (matchesKey(data, Key.escape)) {
					done(null);
				}
			}

			function render(width: number): string[] {
				// The cache MUST be keyed on width: pi-tui calls requestRender() but NOT
				// invalidate() on terminal resize, so render() can be re-entered with a
				// new width. Returning stale wider lines trips the TUI width guard and
				// crashes the process.
				if (cachedLines && cachedWidth === width) return cachedLines;

				// 题目与选项画在会话正文里（renderQuizLive），这里只留操作提示；
				// 要打笔记时才把输入框放到底部。
				const noteFocused = live.focus === "note";
				const lines: string[] = [];
				if (noteFocused) {
					lines.push(...renderEditorBlock(theme, width, "笔记（可选）：", editor));
					lines.push(hintLine(theme, width, "Enter/Tab 返回选项 · Ctrl+J 换行 · Esc 返回"));
				} else if (live.phase === "feedback") {
					lines.push(hintLine(theme, width, "Enter 继续 · Tab 记笔记"));
				} else {
					lines.push(hintLine(theme, width, "↑↓ 选择 · Enter 确认 · Tab 记笔记 · Esc 取消"));
				}

				// 笔记聚焦时不缓存：编辑器画的是活光标。
				if (noteFocused) {
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

async function askMultiChoice(ctx: any, live: QuizLive): Promise<QuizResponse | null> {
	const options = live.options;
	const dontKnowNav = options.length; // nav index of the "I don't know" row
	const submitNav = options.length + 1; // nav index of the "Send" row

	return ctx.ui.custom<QuizResponse | null>(
		(tui: any, theme: any, _kb: any, done: (result: QuizResponse | null) => void) => {
			const editor = makeNoteEditor(tui, theme);
			let cachedLines: string[] | undefined;
			let cachedWidth = -1;

			function refresh() {
				cachedLines = undefined;
				bumpQuiz(live);
				tui.requestRender();
			}

			function toOptions() {
				live.focus = "options";
				editor.focused = false;
				refresh();
			}

			function response(): QuizResponse {
				const note = noteOf(live);
				return liveDontKnow(live)
					? { dontKnow: true, note, answers: [] }
					: { dontKnow: false, note, answers: liveRealAnswers(live) };
			}

			// "I don't know" is exclusive: choosing it clears real selections, and
			// choosing any real option clears "I don't know".
			function toggleOption(index: number) {
				if (index === dontKnowNav) {
					if (live.selected.has(DONT_KNOW_KEY)) {
						live.selected.delete(DONT_KNOW_KEY);
					} else {
						live.selected.clear();
						live.selected.set(DONT_KNOW_KEY, {
							label: DONT_KNOW_LABEL,
							value: DONT_KNOW_VALUE,
							index: DONT_KNOW_INDEX,
						});
					}
				} else {
					const key = `option:${index}`;
					live.selected.delete(DONT_KNOW_KEY);
					if (live.selected.has(key)) {
						live.selected.delete(key);
					} else {
						const option = options[index];
						live.selected.set(key, { label: option.label, value: option.value, index: index + 1 });
					}
				}
				refresh();
			}

			function submit() {
				if (live.selected.size === 0) return;
				live.phase = "feedback";
				refresh();
			}

			function handleInput(data: string) {
				if (live.phase === "feedback") {
					// Tab toggles focus between the static result view and the note
					// field: the user may want to comment on the explanation itself.
					if (matchesKey(data, Key.tab)) {
						live.focus = live.focus === "options" ? "note" : "options";
						editor.focused = live.focus === "note";
						refresh();
						return;
					}
					if (live.focus === "note") {
						if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
							toOptions();
							return;
						}
						editor.handleInput(data);
						live.note = editor.getText();
						refresh();
						return;
					}
					if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
						done(response());
					}
					return;
				}

				// Tab toggles focus between the options list and the note field.
				if (matchesKey(data, Key.tab)) {
					live.focus = live.focus === "options" ? "note" : "options";
					editor.focused = live.focus === "note";
					refresh();
					return;
				}

				if (live.focus === "note") {
					// Enter and Esc both return to the options and keep the note text.
					// (Enter must be intercepted here: the editor's own submit clears
					// the buffer. Ctrl+J still reaches the editor as a newline.)
					if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
						toOptions();
						return;
					}
					editor.handleInput(data);
					live.note = editor.getText();
					refresh();
					return;
				}

				// focus === "options"
				if (matchesKey(data, Key.up)) {
					live.cursor = Math.max(0, live.cursor - 1);
					refresh();
					return;
				}
				if (matchesKey(data, Key.down)) {
					live.cursor = Math.min(submitNav, live.cursor + 1);
					refresh();
					return;
				}

				if (matchesKey(data, Key.enter)) {
					if (live.cursor === submitNav) {
						submit();
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
				// The cache MUST be keyed on width: pi-tui calls requestRender() but NOT
				// invalidate() on terminal resize, so render() can be re-entered with a
				// new width. Returning stale wider lines trips the TUI width guard and
				// crashes the process.
				if (cachedLines && cachedWidth === width) return cachedLines;

				// 题目与选项画在会话正文里（renderQuizLive），这里只留操作提示。
				const noteFocused = live.focus === "note";
				const lines: string[] = [];
				if (noteFocused) {
					lines.push(...renderEditorBlock(theme, width, "笔记（可选）：", editor));
					lines.push(hintLine(theme, width, "Enter/Tab 返回选项 · Ctrl+J 换行 · Esc 返回"));
				} else {
					if (live.phase === "select" && live.selected.size === 0) {
						lines.push(truncateToWidth(theme.fg("warning", " 至少选一项再 Send"), width));
					}
					lines.push(
						hintLine(
							theme,
							width,
							live.phase === "feedback"
								? "Enter 继续 · Tab 记笔记"
								: "↑↓ 移动 · Enter 勾选 · Send 提交 · Tab 记笔记 · Esc 取消",
						),
					);
				}

				// 笔记聚焦时不缓存：编辑器画的是活光标。
				if (noteFocused) {
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

function sortAnswers(answers: OptionAnswer[]): OptionAnswer[] {
	return [...answers].sort((a, b) => a.index - b.index);
}

// Shared UI mutex. ctx.ui.custom()/editor can only handle one active call at
// a time, so ALL pop-up-style tools (quiz, ask_user_question, ...) must
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
	return g[SHARED_UI_LOCK_KEY] as { withLock<T>(fn: () => T | Promise<T>): Promise<T> };
}
const sharedUiLock = getSharedUiLock();

function withUILock<T>(fn: () => Promise<T>): Promise<T> {
	return sharedUiLock.withLock(fn);
}

export default function quiz(pi: ExtensionAPI) {
	pi.registerTool({
		name: "quiz",
		label: "quiz",
		description:
			"Ask the user a GRADED question with a known correct answer, then instantly grade and give feedback. Unlike ask_user_question (which collects preferences/decisions with no right answer), quiz always has a correct answer supplied by you, marks the user's selection right/wrong (✓/✗), reveals the correct answer, and can show an explanation. Use it to (1) assess what the learner already understands before teaching, and (2) run tight practice/retrieval loops after explaining, or probe understanding whenever you're unsure they've got it. Options-only: single-select or multi-select, plus an automatic 'I don't know' choice so the user can signal a genuine gap instead of guessing. An always-present optional note field (Tab to focus it) lets the user attach a free-text note to ANY answer; it reaches you only when non-empty. No free-text answers — for non-graded questions use ask_user_question instead.",
		promptSnippet:
			"Use the quiz tool to test the user with a graded multiple-choice or multi-select question (required correct answer + required explanation). For non-graded questions, use ask_user_question.",
		promptGuidelines: [
			"quiz is GRADED; ask_user_question is not. If the question has a correct answer, use quiz. If you just need a preference, decision, or open-ended input, use ask_user_question.",
			'correctAnswer is REQUIRED and is the option value, not a position number. Single-select: one string (e.g. "mercury"). Multi-select: an array of strings (e.g. ["belize", "niue"]).',
			"Always pass the option's `value` string as correctAnswer — it is self-checking and prevents miscounting positions. A value that matches no option is a hard error.",
			"explanation is REQUIRED — always say why the correct answer is correct.",
			"In `explanation`, NEVER refer to options by letter (A/B/C/D) or by position number: options are shuffled before display, so any letter or number you have in mind does NOT match what the user sees on screen. Refer to options by quoting or briefly summarizing their content instead (e.g. 「王某欠缺表示意识」这一项).",
			"Multi-select is graded as an exact-set match: the user is correct only if they select every correct option and no incorrect ones.",
			"There is no free-text mode. An 'I don't know' choice is ALWAYS added automatically — provide ONLY the real, gradable options (at least two). Never add your own uncertainty/opt-out option like 'I don't know', 'I'm not sure', or 'Not sure'; that is handled for you and a manual one would be redundant or gradable-as-wrong.",
			"If a result comes back as dontKnow, the user honestly did not know and did NOT guess — treat it as a genuine knowledge gap to teach into, not as a wrong answer.",
			"Any answer (right, wrong, or 'I don't know') may carry an optional free-text `note` the user typed in the always-present note field. When present it reflects what they were thinking or unsure about — read it and let it steer your follow-up. It is omitted entirely when empty.",
			"Treat each wrong answer (distractor) as a diagnostic probe, not just filler: make it a specific, believable mistake the user might actually hold — a common misconception, or an adjacent/easily-confused concept — so that WHICH wrong answer they pick reveals WHICH nuance of their understanding is off. You learn far more from a targeted wrong choice than from a binary right/wrong, and the choice tells you exactly which gap to teach into next (and what the explanation should address).",
			"Guardrail: every distractor must be unambiguously wrong on the intended reading — tempting, but a real error, not a defensible alternative. Don't drift into trick questions.",
			"Anti-guessing hygiene: don't let the correct answer stand out by form (longest, most precise, most hedged, or the only one in the right format). Keep options similar in length, specificity, and phrasing so it can't be picked from shape alone.",
			"Set multiSelect: true only when more than one option is correct.",
			"Options are shuffled before display by default, so don't worry about which position you list the correct answer in. Set shuffle: false only when option order is meaningful (ordered values, or an 'All/None of the above' option that must stay last).",
			"To probe nuance, ask several quick quiz questions and adapt each one based on the previous answers, rather than writing one giant question.",
			"Don't leak the answer through formatting: keep option phrasing/length even and don't hint which is correct.",
		],
		parameters: QuizParams,

		async execute(toolCallId, params, signal, onUpdate, ctx) {
			const context = params.details?.trim() || undefined;
			const explanation = normalizeEscapedNewlines(params.explanation ?? "").trim();
			const mode: QuizMode = params.multiSelect ? "multi-select" : "single-select";

			let options: QuizOption[];
			try {
				options = normalizeOptions(params.options);
			} catch (e) {
				return unavailableResult(params.question, mode, `quiz ${(e as Error).message}`, [], context);
			}

			// Shuffle for display (default on) BEFORE resolving correct indices, so
			// grading matches the order the user sees.
			if (params.shuffle !== false) {
				options = shuffleOptions(options);
			}

			const { indices: correctIndices, error: correctError } = resolveCorrect(
				params.correctAnswer as string | string[],
				options,
			);

			if (signal?.aborted) {
				return cancelledResult(params.question, mode, correctIndices, context);
			}

			if (options.length < 2) {
				return unavailableResult(
					params.question,
					mode,
					"quiz requires at least two options",
					correctIndices,
					context,
				);
			}

			if (correctError) {
				return unavailableResult(params.question, mode, `quiz ${correctError}`, correctIndices, context);
			}

			if (!ctx.hasUI) {
				return unavailableResult(params.question, mode, "quiz requires interactive mode UI", correctIndices, context);
			}

			// Emit the true (post-shuffle) display order immediately, before the UI
			// blocks on the user's answer. Listeners such as md-log rely on this to
			// show the question in the SAME order the user actually sees it, instead
			// of the pre-shuffle order the agent originally wrote in its tool call.
			// Deliberately omits correctIndices/explanation — this fires before the
			// user has answered and must not leak the answer.
			// NOTE: this MUST come after all validation above (P2-17): emitting it
			// early made md-log write the question before an invalid quiz
			// (bad correctAnswer / <2 options) bailed out, leaving an orphan
			// question block in the note with no answer to follow it.
			onUpdate?.({
				content: [{ type: "text", text: "Awaiting user response..." }],
				details: { options: options.map((o, i) => ({ index: i + 1, label: o.label })) },
			});

			const live: QuizLive = {
				toolCallId,
				question: params.question,
				context,
				options,
				correctIndices,
				explanation,
				multi: mode === "multi-select",
				cursor: 0,
				phase: "select",
				focus: "options",
				chosen: null,
				dontKnow: false,
				selected: new Map(),
				note: "",
				version: 0,
			};
			quizLive.set(toolCallId, live);

			try {
				return await withUILock(async () => {
					const response =
						mode === "single-select" ? await askSingleChoice(ctx, live) : await askMultiChoice(ctx, live);
					if (!response) {
						return cancelledResult(params.question, mode, correctIndices, context);
					}
					return buildResult(params.question, context, mode, options, response, correctIndices, explanation);
				});
			} finally {
				// 正文那一行随即回落到静态标题（题目/选项/✓✗/解析由 renderResult 复述）。
				quizLive.delete(toolCallId);
			}
		},

		renderCall(args, theme, context) {
			// NOTE: never render correctAnswer or explanation here — it would leak
			// the answer into the transcript before the user responds. The live view
			// (renderQuizLive) draws only the stem, the options in their true shuffled
			// order, and — once the user has answered — the graded feedback. After the
			// tool returns, renderResult restates the whole question with ✓/✗ and the
			// explanation, so the call row falls back to the plain one-line title.
			const id = context.toolCallId;
			const current = () => quizLive.get(id);
			return new LiveLines(
				() => {
					const live = current();
					return live ? `live:${live.version}:${live.phase}` : "static";
				},
				(width) => {
					const live = current();
					return live ? renderQuizLive(theme, width, live) : renderQuizStatic(theme, width, args);
				},
			);
		},

		renderResult(result, _options, theme) {
			const details = result.details as QuizResultDetails | undefined;
			if (!details) {
				const first = result.content[0];
				return new Text(first?.type === "text" ? first.text : "", 0, 0);
			}

			if (details.status === "cancelled") {
				return new Text(theme.fg("warning", details.message || "Cancelled"), 0, 0);
			}
			if (details.status === "unavailable") {
				return new Text(theme.fg("warning", details.message || "quiz unavailable"), 0, 0);
			}

			const correctSet = new Set(details.correctIndices);
			const selectedSet = new Set(details.answers.map((a) => a.index));
			const lines: string[] = [];

			// Re-state the question stem with the feedback so the result block is
			// self-contained: after answering, the stem is no longer on screen, and
			// any correction/explanation is read alongside this block.
			lines.push(theme.fg("text", details.question));
			if (details.context) {
				lines.push(theme.fg("muted", details.context));
			}
			lines.push("");

			// Full option list in the true (shuffled) display order, with ✓/✗ marks.
			// Falls back to just the selected answers for older results that predate
			// details.options.
			const displayed =
				details.options && details.options.length > 0
					? details.options
					: details.answers.map((a) => ({ index: a.index, label: a.label }));

			for (const opt of displayed) {
				const isSelected = selectedSet.has(opt.index);
				const isKey = correctSet.has(opt.index);
				let mark: string;
				let body: string;
				if (details.dontKnow) {
					// No guess — only reveal the correct answer(s); never show ✗.
					mark = isKey ? theme.fg("success", "✓ ") : "  ";
					body = isKey ? theme.fg("success", `${opt.index}. ${opt.label}`) : theme.fg("dim", `${opt.index}. ${opt.label}`);
				} else if (isSelected && isKey) {
					mark = theme.fg("success", "✓ ");
					body = theme.fg("accent", `${opt.index}. ${opt.label}`);
				} else if (isSelected && !isKey) {
					mark = theme.fg("error", "✗ ");
					body = theme.fg("error", `${opt.index}. ${opt.label}`);
				} else if (!isSelected && isKey) {
					mark = theme.fg("success", "✓ ");
					body = theme.fg("success", `${opt.index}. ${opt.label}`);
				} else {
					mark = "  ";
					body = theme.fg("dim", `${opt.index}. ${opt.label}`);
				}
				lines.push(`${mark}${body}`);
			}

			lines.push("");
			const verdict = details.dontKnow
				? theme.fg("warning", "I don't know")
				: details.correct
					? theme.fg("success", "Correct!")
					: theme.fg("error", "Incorrect");
			lines.push(verdict);

			if (details.note) {
				lines.push(theme.fg("muted", `Note: ${details.note}`));
			}

			if (details.explanation) {
				lines.push(theme.fg("muted", details.explanation));
			}

			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
