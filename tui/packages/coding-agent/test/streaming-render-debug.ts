import type { AssistantMessage } from "@cortexagent/ai";
import { ProcessTerminal, type TUI, TuiMainScreen } from "@cortexagent/tui";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { AssistantMessageComponent } from "../src/modes/interactive/components/assistant-message.ts";
import { initTheme } from "../src/modes/interactive/theme/theme.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

process.env.COLORTERM = "truecolor";
initTheme("dark");

const fixtureMessage: AssistantMessage = JSON.parse(
	readFileSync(join(__dirname, "fixtures/assistant-message-with-thinking-code.json"), "utf-8"),
);

const thinkingContent = fixtureMessage.content.find((c) => c.type === "thinking");
const textContent = fixtureMessage.content.find((c) => c.type === "text");

if (!thinkingContent || thinkingContent.type !== "thinking") {
	console.error("No thinking content in fixture");
	process.exit(1);
}

const fullThinkingText = thinkingContent.thinking;
const fullTextContent = textContent && textContent.type === "text" ? textContent.text : "";

async function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
	const terminal = new ProcessTerminal();
	const tui: TUI = new TuiMainScreen(terminal);

	const message = {
		role: "assistant",
		content: [{ type: "thinking", thinking: "" }],
	} as AssistantMessage;

	const component = new AssistantMessageComponent(message, false);
	tui.addChild(component);
	tui.start();

	let thinkingBuffer = "";
	const chunkSize = 10;

	for (let i = 0; i < fullThinkingText.length; i += chunkSize) {
		thinkingBuffer += fullThinkingText.slice(i, i + chunkSize);

		const updatedMessage = {
			role: "assistant",
			content: [{ type: "thinking", thinking: thinkingBuffer }],
		} as AssistantMessage;

		component.updateContent(updatedMessage);
		tui.requestRender();

		await sleep(15);
	}

	await sleep(500);

	const finalMessage = {
		role: "assistant",
		content: [
			{ type: "thinking", thinking: fullThinkingText },
			{ type: "text", text: fullTextContent },
		],
	} as AssistantMessage;

	component.updateContent(finalMessage);
	tui.requestRender();

	await sleep(3000);

	tui.stop();
	process.exit(0);
}

main().catch(console.error);
