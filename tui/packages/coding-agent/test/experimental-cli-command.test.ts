import { describe, expect, test } from "vitest";
import { experimentalCli } from "../src/cli/experimental/cli.ts";

describe("experimental CLI commands", () => {
	test("selects cortex mode and parses existing CLI arguments", () => {
		expect(
			experimentalCli.parse([
				"--provider",
				"anthropic",
				"--model",
				"claude-sonnet",
				"--thinking",
				"high",
				"inspect",
				"the project",
			]),
		).toMatchObject({
			ok: true,
			command: {
				command: "cortex",
				options: {
					provider: "anthropic",
					model: "claude-sonnet",
					thinking: "high",
					messages: ["inspect", "the project"],
				},
			},
		});
	});

	test("parses a server listener", () => {
		expect(experimentalCli.parse(["server", "--listen", "unix:///tmp/cortex.sock"])).toEqual({
			ok: true,
			command: {
				command: "server",
				listen: [{ transport: "unix", path: "/tmp/cortex.sock" }],
			},
		});
	});

	test("leaves experimental-looking existing option values with the existing parser", () => {
		expect(experimentalCli.parse(["--system-prompt", "--listen", "unix:///tmp/cortex.sock"])).toMatchObject({
			ok: true,
			command: {
				command: "cortex",
				options: { systemPrompt: "--listen", messages: ["unix:///tmp/cortex.sock"] },
			},
		});
	});

	test("stops parsing command options when existing CLI arguments begin", () => {
		const result = experimentalCli.parse(["--model", "claude-sonnet", "--listen=unix:///tmp/second.sock"]);
		expect(result).toMatchObject({
			ok: true,
			command: { command: "cortex", options: { model: "claude-sonnet" } },
		});
		if (!result.ok || result.command.command !== "cortex") return;
		expect(result.command.listen).toBeUndefined();
		expect(result.command.options.unknownFlags.get("listen")).toBe("unix:///tmp/second.sock");
	});

	test("parses a client transport address", () => {
		expect(experimentalCli.parse(["client", "--connect", "unix:///tmp/cortex.sock"])).toEqual({
			ok: true,
			command: {
				command: "client",
				connect: { transport: "unix", path: "/tmp/cortex.sock" },
			},
		});
	});

	test.each([
		[["--auth-token", "secret"], { type: "token", token: "secret" }],
		[["--auth-token-file", "/tmp/token"], { type: "file", path: "/tmp/token" }],
	] as const)("parses authentication source %j", (argv, auth) => {
		expect(experimentalCli.parse(argv)).toMatchObject({
			ok: true,
			command: { command: "cortex", auth },
		});
	});

	test.each([[[]], [["server"]], [["client"]]] as const)(
		"permits omitted authentication for later environment/default resolution",
		(argv) => {
			const result = experimentalCli.parse(argv);
			expect(result).toMatchObject({ ok: true, command: { command: argv[0] ?? "cortex" } });
			if (result.ok) expect(result.command.auth).toBeUndefined();
		},
	);

	test("passes unknown options, file arguments, and the positional separator to the existing parser", () => {
		const result = experimentalCli.parse(["--unknown", "@prompt.md", "--", "--listen", "unix:///tmp/cortex.sock"]);
		expect(result).toMatchObject({
			ok: true,
			command: { command: "cortex", options: { fileArgs: ["prompt.md"] } },
		});
		if (!result.ok || result.command.command !== "cortex") return;
		expect(result.command.options.unknownFlags.get("unknown")).toBe(true);
		expect(result.command.options.unknownFlags.get("listen")).toBe("unix:///tmp/cortex.sock");
	});

	test.each([
		[
			["--listen", "unix:///tmp/cortex.sock", "--listen", "unix:///tmp/cortex-admin.sock"],
			"--listen may only be specified once",
		],
		[
			["--auth-token", "secret", "--auth-token-file", "/tmp/token"],
			"--auth-token and --auth-token-file are mutually exclusive",
		],
		[["--auth-token", "first", "--auth-token", "second"], "--auth-token may only be specified once"],
		[
			["--auth-token-file", "/tmp/first", "--auth-token-file=/tmp/second"],
			"--auth-token-file may only be specified once",
		],
		[["--listen", "/tmp/cortex.sock"], 'Invalid --listen address "/tmp/cortex.sock"'],
		[["--listen", "ws://localhost:8080"], 'Unsupported --listen transport "ws:"'],
		[["--listen", "unix://relative.sock"], "Unix transport address must not include an authority"],
		[
			["--listen", "unix:///tmp/cortex.sock?wrong=value"],
			'Invalid --listen address "unix:///tmp/cortex.sock?wrong=value"',
		],
		[["--listen", "unix:///tmp/cortex.sock#fragment"], 'Invalid --listen address "unix:///tmp/cortex.sock#fragment"'],
		[["--listen", "unix:/tmp/cortex.sock"], 'Invalid --listen address "unix:/tmp/cortex.sock"'],
		[["--listen", "unix:///tmp/%00cortex.sock"], 'Invalid --listen address "unix:///tmp/%00cortex.sock"'],
		[
			["client", "--listen", "unix:///tmp/cortex.sock"],
			"The experimental client command does not support existing CLI options yet",
		],
		[
			["server", "--connect", "unix:///tmp/cortex.sock"],
			"The experimental server command does not support existing CLI options yet",
		],
		[["client", "--connect", "ws://localhost:8080"], 'Unsupported --connect transport "ws:"'],
		[["--listen"], "--listen requires a value"],
		[["--connect="], "--connect is only valid for client mode"],
	] as const)("rejects invalid experimental input %j", (argv, error) => {
		const result = experimentalCli.parse(argv);
		expect(result).toMatchObject({ ok: false });
		if (!result.ok) expect(result.errors).toContainEqual(expect.stringContaining(error));
	});

	test("rejects unsupported options without parsing them", () => {
		expect(
			experimentalCli.parse([
				"client",
				"--listen",
				"ws://localhost:8080",
				"--auth-token",
				"secret",
				"--auth-token-file",
				"/tmp/token",
			]),
		).toEqual({
			ok: false,
			errors: ["The experimental client command does not support existing CLI options yet"],
		});
	});

	test("treats command names after the first argument as existing CLI arguments", () => {
		expect(experimentalCli.parse(["--cwd", "/workspace", "server"])).toMatchObject({
			ok: true,
			command: { command: "cortex", options: { messages: ["server"] } },
		});
	});
});
