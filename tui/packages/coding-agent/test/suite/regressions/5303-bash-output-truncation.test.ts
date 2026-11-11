import type { ChildProcessByStdio } from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitForChildProcess } from "../../../src/utils/child-process.ts";

describe("issue #5303 bash output truncation past exit", () => {
	function createChild(): ChildProcessByStdio<null, PassThrough, PassThrough> {
		return Object.assign(new EventEmitter(), {
			stdin: null,
			stdout: new PassThrough(),
			stderr: new PassThrough(),
		}) as unknown as ChildProcessByStdio<null, PassThrough, PassThrough>;
	}

	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("captures output emitted after exit while a descendant holds stdout open", async () => {
		const child = createChild();
		let output = "";
		child.stdout.on("data", (chunk: Buffer) => {
			output += chunk.toString();
		});
		let resolved = false;
		const waiting = waitForChildProcess(child).then((exitCode) => {
			resolved = true;
			return exitCode;
		});

		child.stdout.write("HEAD\n");
		child.emit("exit", 0, null);
		for (let index = 1; index <= 6; index++) {
			await vi.advanceTimersByTimeAsync(50);
			child.stdout.write(`TICK${index}\n`);
		}
		await vi.advanceTimersByTimeAsync(99);
		expect(resolved).toBe(false);
		await vi.advanceTimersByTimeAsync(1);

		expect(await waiting).toBe(0);
		expect(output).toContain("HEAD");
		expect(output).toContain("TICK6");
	});

	it("resolves after the grace when a descendant holds stdout open but stays quiet", async () => {
		const child = createChild();
		let resolved = false;
		const waiting = waitForChildProcess(child).then((exitCode) => {
			resolved = true;
			return exitCode;
		});

		child.stdout.write("DONE\n");
		child.emit("exit", 0, null);
		await vi.advanceTimersByTimeAsync(99);
		expect(resolved).toBe(false);
		await vi.advanceTimersByTimeAsync(1);

		expect(await waiting).toBe(0);
	});
});
