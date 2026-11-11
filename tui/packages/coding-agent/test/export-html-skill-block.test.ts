import { readFileSync } from "fs";
import { describe, expect, it } from "vitest";

describe("export HTML skill block rendering", () => {
	const templateJs = readFileSync(new URL("../src/core/export-html/template.js", import.meta.url), "utf-8");

	it("strips skill wrapper XML from user message rendering", () => {
		expect(templateJs).toMatch(/parseSkillBlock/);
		expect(templateJs).toMatch(/skillBlock\.userMessage/);
	});

	it("renders skill invocation and user message as separate sibling blocks", () => {
		expect(templateJs).toMatch(/skill-invocation/);

		expect(templateJs).toMatch(/hasUserContent/);
	});

	it("renders skill content as markdown, not raw text", () => {
		expect(templateJs).toMatch(/safeMarkedParse\(skillBlock\.content\)/);
	});

	it("shows skill name and user message in the sidebar tree", () => {
		expect(templateJs).toMatch(/tree-role-skill/);
	});
});
