import { mkdtempSync, readdirSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { expandPath, resolveReadPath, resolveToCwd } from "../src/core/tools/path-utils.ts";

describe("path-utils", () => {
	describe("expandPath", () => {
		it("should expand ~ to home directory", () => {
			const result = expandPath("~");
			expect(result).not.toContain("~");
		});

		it("should expand ~/path to home directory", () => {
			const result = expandPath("~/Documents/file.txt");
			expect(result).not.toContain("~/");
		});

		it("should keep tilde-prefixed filenames literal", () => {
			expect(expandPath("~draft.md")).toBe("~draft.md");
			expect(expandPath("@~draft.md")).toBe("~draft.md");
		});

		it("should normalize Unicode spaces", () => {
			const withNBSP = "file\u00A0name.txt";
			const result = expandPath(withNBSP);
			expect(result).toBe("file name.txt");
		});
	});

	describe("resolveToCwd", () => {
		it("should resolve absolute paths as-is", () => {
			const absolutePath = resolve(tmpdir(), "absolute", "path", "file.txt");
			const result = resolveToCwd(absolutePath, resolve(tmpdir(), "some", "cwd"));
			expect(result).toBe(absolutePath);
		});

		it("should resolve relative paths against cwd", () => {
			const result = resolveToCwd("relative/file.txt", "/some/cwd");
			expect(result).toBe(resolve("/some/cwd", "relative/file.txt"));
		});

		it("should resolve tilde-prefixed filenames against cwd", () => {
			const cwd = join(tmpdir(), "cortex-path-utils-cwd");
			expect(resolveToCwd("~draft.md", cwd)).toBe(resolve(cwd, "~draft.md"));
			expect(resolveToCwd("@~draft.md", cwd)).toBe(resolve(cwd, "~draft.md"));
		});
	});

	describe("resolveReadPath", () => {
		let tempDir: string;

		beforeEach(() => {
			tempDir = mkdtempSync(join(tmpdir(), "path-utils-test-"));
		});

		afterEach(() => {
			try {
				const files = readdirSync(tempDir);
				for (const file of files) {
					unlinkSync(join(tempDir, file));
				}
				rmdirSync(tempDir);
			} catch {
				// Ignore cleanup errors
			}
		});

		it("should resolve existing file path", () => {
			const fileName = "test-file.txt";
			writeFileSync(join(tempDir, fileName), "content");

			const result = resolveReadPath(fileName, tempDir);
			expect(result).toBe(join(tempDir, fileName));
		});

		it("should handle NFC vs NFD Unicode normalization (macOS filenames with accents)", () => {
			const nfdFileName = "file\u0065\u0301.txt";

			const nfcFileName = "file\u00e9.txt";

			expect(nfdFileName).not.toBe(nfcFileName);
			expect(Buffer.from(nfdFileName)).not.toEqual(Buffer.from(nfcFileName));

			writeFileSync(join(tempDir, nfdFileName), "content");

			const result = resolveReadPath(nfcFileName, tempDir);

			expect(result).toContain(tempDir);
			expect(result).toMatch(/file.+\.txt$/);
		});

		it("should handle curly quotes vs straight quotes (macOS filenames)", () => {
			const curlyQuoteName = "Capture d\u2019cran.txt";
			const straightQuoteName = "Capture d'cran.txt";

			expect(curlyQuoteName).not.toBe(straightQuoteName);

			writeFileSync(join(tempDir, curlyQuoteName), "content");

			const result = resolveReadPath(straightQuoteName, tempDir);
			expect(result).toBe(join(tempDir, curlyQuoteName));
		});

		it("should handle combined NFC + curly quote (French macOS screenshots)", () => {
			const nfcCurlyName = "Capture d\u2019\u00e9cran.txt";
			const nfcStraightName = "Capture d'\u00e9cran.txt";

			expect(nfcCurlyName).not.toBe(nfcStraightName);

			writeFileSync(join(tempDir, nfcCurlyName), "content");

			const result = resolveReadPath(nfcStraightName, tempDir);
			expect(result).toBe(join(tempDir, nfcCurlyName));
		});

		it("should handle macOS screenshot AM/PM variant with narrow no-break space", () => {
			const macosName = "Screenshot 2024-01-01 at 10.00.00\u202FAM.png";
			const userName = "Screenshot 2024-01-01 at 10.00.00 AM.png";

			writeFileSync(join(tempDir, macosName), "content");

			const result = resolveReadPath(userName, tempDir);

			expect(result).toBe(join(tempDir, macosName));
		});

		it("should handle macOS screenshot lowercase am/pm variant (en_AU locale)", () => {
			const macosName = "Screenshot 2024-01-01 at 10.00.00\u202Fam.png";
			const userName = "Screenshot 2024-01-01 at 10.00.00 am.png";

			writeFileSync(join(tempDir, macosName), "content");

			const result = resolveReadPath(userName, tempDir);

			expect(result).toBe(join(tempDir, macosName));
		});
	});
});
