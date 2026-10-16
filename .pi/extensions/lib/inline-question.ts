/**
 * inline-question — 「把题目画进会话正文」的公用零件。
 *
 * 面板时代（旧做法）：题目画在 `ctx.ui.custom()` 的组件里。pi 会把这种组件塞进
 * 底部粘性 dock 的**输入框槽位**（`editorContainer`），dock 高度是 auto、会话区是
 * grow:1，所以面板多高就从会话区抢多高 —— 一屏的下半部分就没了。
 *
 * 现在拆成两条腿：
 *   1. 正文那一行由工具的 `renderCall(args, theme, context)` 画：pi 把工具调用的
 *      call 组件与 result 组件并排画在同一行里，工具结束后 call 组件**仍然保留**，
 *      所以题目会留在会话正文里，跟着消息一起滚动。
 *   2. 屏幕底部只留 `ctx.ui.custom()` 的一行操作提示，负责拿键盘焦点。
 *
 * 两条腿在不同组件里，都得读同一份「现在选到第几项」的状态：状态放
 * `LiveRegistry`（键＝ toolCallId，一次提问一条），两边只读/写它。
 *
 * 注意：本文件按「Node 类型擦除」的语法写（不用参数属性/枚举/命名空间），
 * 这样临时探针脚本能直接 `import` 它。
 */

import { truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";

/**
 * renderCall 返回的组件：按 `keyOf()` 的返回值和 width 缓存行，任何一个变了就重算。
 *
 * 为什么要自检 `keyOf`（挂状态版本号）而不是等 pi 来 invalidate：
 * `context.invalidate()` 只在按键路径上拿得到，而「execute 刚建好状态」「阶段切到
 * done」这些时刻没有它；pi 每帧都会重跑整棵树的 render，所以让组件自己在下一帧
 * 发现版本变了最省事。
 *
 * 缓存必须连 width 一起记：pi 在终端 resize 时只 requestRender、不 invalidate，
 * render 会用新 width 重入，返回宽度不符的旧行会触发 TUI 的宽度校验并崩进程。
 */
export class LiveLines {
	private cachedKey: string | undefined;
	private cached: string[] = [];
	private keyOf: () => string;
	private build: (width: number) => string[];

	constructor(keyOf: () => string, build: (width: number) => string[]) {
		this.keyOf = keyOf;
		this.build = build;
	}

	render(width: number): string[] {
		const key = `${width}\u0000${this.keyOf()}`;
		if (this.cachedKey === key) return this.cached;
		this.cached = this.build(width);
		this.cachedKey = key;
		return this.cached;
	}

	invalidate(): void {
		this.cachedKey = undefined;
	}
}

/** 一次提问的活动状态，键＝ toolCallId（pi 对同一次工具调用稳定）。 */
export class LiveRegistry<T> {
	private map = new Map<string, T>();

	get(id: string): T | undefined {
		return this.map.get(id);
	}

	set(id: string, state: T): void {
		this.map.set(id, state);
	}

	/** 提问结束就删：正文那一行随即回落到静态版，旧的鼠标状态不留着。 */
	delete(id: string): void {
		this.map.delete(id);
	}
}

/** 底部条的一行提示。 */
export function hintLine(theme: any, width: number, text: string): string {
	return truncateToWidth(theme.fg("dim", ` ${text}`), width);
}

/**
 * 正文里的一个选项行：`> 2. 标签 说明`。
 * 说明跟在标签后面（不再是另起一行的缩进块），一行一项 —— 题目再长也不铺满屏幕。
 * 返回未截断的字符串，调用方按 width 截断。
 */
export function optionRow(theme: any, focused: boolean, label: string, description?: string): string {
	const prefix = focused ? theme.fg("accent", "> ") : "  ";
	const body = focused ? theme.fg("accent", label) : theme.fg("text", label);
	const tail = description ? ` ${theme.fg("dim", description)}` : "";
	return `${prefix}${body}${tail}`;
}

/**
 * 底部条展开的小输入框（Other / 笔记）：一行标签 + 编辑器自身的边框与光标。
 * 只在需要打字时出现，平时底部就一行提示。
 */
export function renderEditorBlock(
	theme: any,
	width: number,
	label: string,
	editor: { render(width: number): string[] },
): string[] {
	const lines: string[] = [];
	for (const line of wrapTextWithAnsi(theme.fg("accent", label), Math.max(1, width - 1))) {
		lines.push(truncateToWidth(` ${line}`, width));
	}
	for (const line of editor.render(Math.max(1, width - 2))) {
		lines.push(truncateToWidth(` ${line}`, width));
	}
	return lines;
}
