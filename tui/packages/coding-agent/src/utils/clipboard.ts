import { type ExecFileSyncOptionsWithStringEncoding, execFileSync, execSync, spawn } from "child_process";
import { platform } from "os";
import { isWaylandSession } from "./clipboard-image.ts";
import { clipboard } from "./clipboard-native.ts";

type NativeClipboardExecOptions = {
	input: string;
	timeout: number;
	stdio: ["pipe", "ignore", "ignore"];
};

function copyToX11Clipboard(options: NativeClipboardExecOptions): void {
	try {
		execSync("xclip -selection clipboard", options);
	} catch {
		execSync("xsel --clipboard --input", options);
	}
}

const MAX_OSC52_ENCODED_LENGTH = 100_000;

function isRemoteSession(env: NodeJS.ProcessEnv = process.env): boolean {
	return Boolean(env.SSH_CONNECTION || env.SSH_CLIENT || env.MOSH_CONNECTION);
}

function emitOsc52(text: string): boolean {
	const encoded = Buffer.from(text).toString("base64");
	if (encoded.length > MAX_OSC52_ENCODED_LENGTH) {
		return false;
	}
	process.stdout.write(`\x1b]52;c;${encoded}\x07`);
	return true;
}

type ClipboardReadResult = { ok: true; text: string | null } | { ok: false };

const READ_CLIPBOARD_OPTIONS: ExecFileSyncOptionsWithStringEncoding = {
	encoding: "utf8",
	maxBuffer: 50 * 1024 * 1024,
	timeout: 5000,
};

function readWaylandClipboardText(): ClipboardReadResult {
	try {
		const text = execFileSync("wl-paste", ["--no-newline", "--type", "text"], READ_CLIPBOARD_OPTIONS);
		return { ok: true, text: text || null };
	} catch {
		return { ok: false };
	}
}

export async function readClipboardText(): Promise<string | null> {
	if (platform() === "linux" && isWaylandSession() && process.env.WAYLAND_DISPLAY) {
		const result = readWaylandClipboardText();
		if (result.ok) {
			return result.text;
		}
	}

	if (!clipboard) {
		return null;
	}

	try {
		const text = await clipboard.getText();
		return text || null;
	} catch {
		return null;
	}
}

export async function copyToClipboard(text: string): Promise<void> {
	let copied = false;

	const p = platform();

	try {
		if (clipboard && p !== "linux") {
			await clipboard.setText(text);
			copied = true;
		}
	} catch {
		// Fall through to platform-specific clipboard tools.
	}

	const remote = isRemoteSession();
	if (copied && !remote) {
		return;
	}

	const options: NativeClipboardExecOptions = { input: text, timeout: 5000, stdio: ["pipe", "ignore", "ignore"] };

	if (!copied) {
		try {
			if (p === "darwin") {
				execSync("pbcopy", options);
				copied = true;
			} else if (p === "win32") {
				execSync("clip", options);
				copied = true;
			} else {
				if (process.env.TERMUX_VERSION) {
					try {
						execSync("termux-clipboard-set", options);
						copied = true;
					} catch {
						// Fall back to Wayland or X11 tools.
					}
				}

				if (!copied) {
					const hasWaylandDisplay = Boolean(process.env.WAYLAND_DISPLAY);
					const hasX11Display = Boolean(process.env.DISPLAY);
					const isWayland = isWaylandSession();
					if (isWayland && hasWaylandDisplay) {
						try {
							execSync("which wl-copy", { stdio: "ignore" });

							const wlCopyExit = await new Promise<number>((resolve) => {
								const proc = spawn("wl-copy", [], { stdio: ["pipe", "ignore", "ignore"] });
								proc.on("error", () => resolve(1));
								proc.on("close", (code) => resolve(code ?? 1));
								proc.stdin.on("error", () => {
									// Ignore EPIPE errors if wl-copy exits early
								});
								proc.stdin.write(text);
								proc.stdin.end();
							});
							if (wlCopyExit === 0) {
								copied = true;
							} else if (hasX11Display) {
								copyToX11Clipboard(options);
								copied = true;
							}
						} catch {
							if (hasX11Display) {
								copyToX11Clipboard(options);
								copied = true;
							}
						}
					} else if (hasX11Display) {
						copyToX11Clipboard(options);
						copied = true;
					}
				}
			}
		} catch {
			// Fall through to OSC 52 fallback.
		}
	}

	if (remote || !copied) {
		const osc52Copied = emitOsc52(text);
		copied = copied || osc52Copied;
	}

	if (!copied) {
		throw new Error("Failed to copy to clipboard");
	}
}
