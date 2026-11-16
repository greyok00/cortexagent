import { createModels } from "../src/models.ts";
import { anthropicProvider } from "../src/providers/anthropic.ts";
import type { Context } from "../src/types.ts";

const models = createModels();
models.setProvider(anthropicProvider());

const model = models.getModel("anthropic", "claude-haiku-4-5");
if (!model) throw new Error("model not found");

const auth = await models.getAuth(model.provider);
console.log(`model: ${model.provider}/${model.id}`);
console.log(`auth:  ${auth ? `configured via ${auth.source}` : "not configured"}\n`);
if (!auth) process.exit(1);

const context: Context = {
	systemPrompt: "You are terse.",
	messages: [{ role: "user", content: "Say exactly: ok", timestamp: Date.now() }],
};

const message = await models.completeSimple(model, context);
console.log(`completeSimple -> [${message.stopReason}]`, message.content);

context.messages.push(message, {
	role: "user",
	content: "Now count from 1 to 5, one number per line.",
	timestamp: Date.now(),
});

process.stdout.write("streamSimple   -> ");
const stream = models.streamSimple(model, context);
for await (const event of stream) {
	if (event.type === "text_delta") process.stdout.write(event.delta.replaceAll("\n", " "));
}
const final = await stream.result();
console.log(`[${final.stopReason}] cost: $${final.usage.cost.total.toFixed(6)}`);
