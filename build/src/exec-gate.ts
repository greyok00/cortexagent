import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

// In-memory mirror of the folder law (state file is the boot source).
let currentRoot: string | null = null;
let lastOwnerText = "";
let lastOwnerTs = 0;

// exec-gate.ts — GA-11 (2026-11-03): the bash lane was the one path where
// model decisions reached the OS with a timeout cap and zero rules. This
// extension hooks the tool_call event and refuses bash/shell calls that
// violate a read-only allowlist, mirroring build/src/registry.py's core
// gate so both lanes enforce one policy (spawn_subagent lane = TUI lane).
// 2026-11-10 (owner order, after the Good Twin loop): THREE owner directives
// land here permanently:
//   1. `&&` chaining is ALLOWED — every && segment is validated one by one,
//      no per-segment refuser for the chain form itself.
//   2. `cd` is a first-class allowlisted command (it was implicit-only before;
//      the visual-companion launch recipe required cd && and got refused forever).
//   3. THE FOLDER LAW: when the OWNER names a project folder ("restrict
//      yourselfe to just this folder", "stay in X", "only work in X"), the
//      gate anchors to it and every bash/read/edit/write path must live
//      inside that root (or the machine-legit escapes below). "you're free"
//      / "no folder restriction" clears the anchor. Refusals tell the model
//      to ASK THE OWNER, which converts a doomed retry-loop into a real
//      question.

// ---------- folder law ----------

const LAW_PATH = path.join(os.homedir(), ".cortex-agent", "agent", "state", "workspace-root");

// Owner phrases that ANCHOR the session to a folder. Two shapes matched
// (both verified against real owner messages):
//   words-then-path : “stay in /home/x/y”, “restrict yourself to /x”
//   path-then-words : “/home/grey/Desktop/good-twin ok restrict yourselfe
//                     to just this folder” (Good Twin, 2026-11-10)
// A message needs BOTH restriction language and a path (or a quoted path).
const RESTR_RE =
	/\b(?:restrict|confine|stay|remain|work\s+only|only\s+(?:work|use|in)|keep(?:\s+yourself)?\s+to|this\s+folder|this\s+project)\b/i;
const ABS_PATH_RE = /(?:~\/?|\/)[\w.\-]+(?:\/[\w.\-+]+)*/g;
// Owner phrases that CLEAR the anchor ("you're free" / "you are free" — note
// "you're" has NO space between you and 're, so \s* not \s+):
const CLEAR_RE = /\byou\s*(?:are|'?re?)\s+free\b|\bno folder restriction\b|\bfolder restriction lifted\b|\bany folder\b/i;

function loadLaw(): string | null {
	try {
		const v = fs.readFileSync(LAW_PATH, "utf8").trim();
		return v || null;
	} catch {
		return null;
	}
}

function saveLaw(root: string | null): void {
	try {
		fs.mkdirSync(path.dirname(LAW_PATH), { recursive: true });
		if (root) fs.writeFileSync(LAW_PATH, root + "\n");
		else fs.unlinkSync(LAW_PATH);
	} catch {
		/* state file best-effort; the in-memory copy still governs this process */
	}
}

// /tmp, /dev/null and tool-harness dirs are legitimate escapes from the
// anchor (build logs, tempfiles). The agent's OWN home (skills, extensions,
// APPEND_SYSTEM, state) is its operating equipment — the Good Twin demo
// anchored to a project while the brain still legitimately read its skill
// system. Everything else must be inside the anchor.
const LAW_EXEMPT = [
	"/tmp/", "/dev/null", "/proc/", "/sys/", "/dev/shm/",
	path.join(os.homedir(), ".cortex-agent") + "/",
];

function extractQuotedRoot(text: string): string | null {
	// "restrict yourself to just `/home/x/y`" — backticked or quoted wins first
	const m = text.match(/[`"']((?:\/|~)[\w.\-\/+]+)[`"']/);
	return m ? m[1] : null;
}

function expandRoot(raw: string): string | null {
	const p = raw.startsWith("~") ? path.join(os.homedir(), raw.slice(1)) : raw;
	try {
		const rp = fs.realpathSync.native(path.resolve(p));
		return fs.statSync(rp).isDirectory() ? rp : null;
	} catch {
		return null;
	}
}

// One anchor attempt per owner user-message (end event), so the model's own
// recaps and steering notes can NEVER set or clear the law.
function handleOwnerMessage(content: string): void {
	if (CLEAR_RE.test(content)) {
		saveLaw(null);
		currentRoot = null;
		return;
	}
	if (!RESTR_RE.test(content)) return;
	const quoted = extractQuotedRoot(content);
	let raw: string | null = quoted ?? null;
	if (!raw) {
		const m = ABS_PATH_RE.exec(content);
		raw = m ? m[0] : null;
	}
	if (!raw) return;
	const root = expandRoot(raw);
	if (!root || root === os.homedir()) return; // home itself is not an anchor
	saveLaw(root);
	currentRoot = root;
}

function pathInsideRoot(p: string, root: string): boolean {
	const rel = path.relative(root, p);
	return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

function lawCheck(p: string): { ok: true } | { ok: false; reason: string } {
	const root = currentRoot ?? loadLaw();
	if (!root) return { ok: true };
	if (!path.isAbsolute(p)) return { ok: true }; // model-cwd-relative: resolved at checkSingle time
	const rp = (() => {
		try {
			return fs.realpathSync.native(path.resolve(p));
		} catch {
			return path.resolve(p); // not-yet-existing paths (new files) resolve lexically
		}
	})();
	if (LAW_EXEMPT.some((e) => rp.startsWith(e))) return { ok: true };
	if (pathInsideRoot(rp, root)) return { ok: true };
	return {
		ok: false,
		reason:
			`refused: "${p}" is outside the owner-restricted folder (${root}). ` +
			`The folder law is active. Work inside ${root}, or TELL THE OWNER you need a path ` +
			`outside it and wait for their answer — do not retry or work around this.`,
	};
}

// paths to check on every bash call: every /absolute/ or relative token
function lawCheckCmd(c: string): string | null {
	const root = currentRoot ?? loadLaw();
	if (!root) return null;
	for (const tok of c.split(/\s+/)) {
		const t = tok.replace(/^["']|["']$/g, "");
		const isPathish = t.startsWith("/") || t.startsWith("./") || t.startsWith("../") || t.startsWith("~");
		if (!isPathish) continue;
		// flags are not paths (e.g. -source, --project-dir=value handled: bare --x skipped)
		if (t.startsWith("-")) continue;
		const abs = t.startsWith("~") ? path.join(os.homedir(), t.slice(1)) : path.resolve(t);
		const check = lawCheck(abs);
		if (!check.ok) return check.reason;
	}
	return null;
}

// ---------- bash allowlist (unchanged policy, +cd) ----------

const SAFE_BINS = new Set([
	"cd", "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "date", "du",
	"df", "free", "ps", "wc", "stat", "echo", "file", "which", "env",
	"printenv", "uname", "whoami", "id", "uptime", "hostname", "arch",
	"nproc", "sort", "uniq", "cut", "tr", "comm", "sha256sum", "md5sum",
	"base64", "xargs", "diff", "git", "ss", "ip", "lsof", "nvidia-smi",
	"taskset", "sleep", "mkdir",
	// 2026-11-06 owner: the agent needs to download, unpack and inspect
	// targets itself (smoothcsv download + decompile class). Network fetches,
	// archive extraction, a second analysis tier and the workspace mkdir.
	// python3 is an interpreter — its inclusion here is an explicit
	// trust-level expansion, not a read-only extension.
	"curl", "wget", "unzip", "tar", "python3",
	"strings", "nm", "objdump", "readelf",
	// 2026-11-06 owner: agent stalled on "cp not in allow list" during the
	// APK red-team session. File operations stay narrow-path (the redirect
	// policy above already confines > to /tmp and /dev/null); rm/deliberate
	// mutation of user files still go through the file tools, which is
	// unchanged policy.
	"cp", "mv", "touch", "dirname", "basename", "realpath", "readlink",
	"awk", "sed", "tee",
	// 2026-11-09 owner: the APK lane needed a whole ring of the toolchain
	// and its refusals were the 20x loop fuel. Read-only device probing,
	// process census and the APK/jar/keystore toolchain.
	"adb", "pgrep", "pidof", "hexdump", "xxd", "less", "test", "seq", "bc",
	"aapt2", "apkanalyzer", "./gradlew", "gradle", "java", "keytool", "d8",
	"javac", "jarsigner", "zipinfo",
	// 2026-11-09 (APK rebuild incident, second wave): the build script needs
	// plain aapt (not aapt2), zip, zipalign and apksigner — all were refused
	// because they were never listed.
	"aapt", "apksigner", "zip", "zipalign",
	// 2026-11-10 owner: "i want it to have more commands" — the APK lane
	// needs python (single scripts only, never -c heredocs), the build chain
	// (make), node, npx, env inspection, pids, dirs, tree, and the shell
	// builtin test. sleep/test were always safe; python3/python stay
	// interpreter-tier trust (owner-approved) and run single-line only.
	"python", "make", "node", "npx", "tree", "wc", "test",
	// 2026-11-10 owner (kb-library port incident): ad-hoc servers are BANNED.
	// `python3 -m http.server <port>` hijacked the knowledge library's :8792
	// and was presented as "the visual companion". Serving directories is
	// never the bash lane's job: the visual companion has its own start-server
	// script (random port, key-gated), the library portal /8792/ is owned by
	// the library extension. python3 stays allowlisted for scripts, but the
	// http.server / ftp.server / socketserver modules are refused outright.
]);

// Ports that are NEVER available to ad-hoc servers or rebinds. The owner's
// standing law (2026-11-10): once a service owns a port, the agent never
// starts anything else on it, and never "overwrites the port or its files".
const RESERVED_PORTS: Record<string, string> = {
	"8791": "greysearch portal (knowledge)",
	"8792": "knowledge library UI (library.ts extension owner)",
	"7100": "cortex engine (llama server)",
	"7101": "slimtoken lane",
	"8972": "kb-ingest library (sibling)",
	"8000": "mobsf (mobile security framework)",
	"9390": "sg-theme wp site",
	"9391": "v107-sentinel wp site",
	"9392": "v107-faang wp site",
	"8095": "bs-audit wp site",
	"8083": "wp site (wp-app)",
	"8084": "wp site (automart-app)",
	"8085": "wp site (bespoke-app)",
	"8086": "wp site (cellfix-app)",
	"8087": "wp site (folio-app)",
	"8089": "wp site (umami-app)",
	"3307": "mariadb wp-db", "3308": "mariadb automart-db", "3309": "mariadb bespoke-db",
	"3310": "mariadb cellfix-db", "3311": "mariadb folio-db", "3313": "mariadb umami-db",
};
const ADB_READ_SUBS = new Set([
	"devices", "get-state", "shell", "logcat", "bugreport", "version",
	"install", "uninstall", "push", "pull",
]);
const GIT_SAFE_SUB = new Set([
	"status", "diff", "log", "show", "blame", "branch", "rev-parse", "ls-files",
]);
const NEVER_RE =
	// 2026-11-11 (token-rate incident, owner: "extremely higher than normal,
	// repeats and truncations"): \bsh\b / \bbash\b as substring-matched inside
	// FILENAMES (`cat build-all.sh`, `head start-server.sh`) sent every read-
	// only call into the interpreter refusal → the model retried dozens of
	// variations → 47x identical refusals in-context → multi-megabyte prompt
	// re-sends every turn. Interpreter names must match as COMMAND tokens
	// (beginning of the string or after a shell separator), never as a
	// mid-path fragment. Same for /bin/sh-style absolute interpreters.
	/mkfs|\bdd\b(?=[\s]|$)|\bkillall\b|\bsystemctl\b|\bservice\b(?![\w.-])|\bpkexec\b|\beval\b|(?<!-)\bsource\b|\btmux\b|\bsetsid\b|\bapt-get\b|\baptitude\b|\bflatpak\b|\bsnap\b|(^|[;&|]\s*|\/bin\/)(sh|bash|zsh|fish|dash)\b(?=\s|$)/;
// 2026-11-09 (APK rebuild incident): two regexes were over-broad. `\source`
// caught javac's `-source 21` flag (now lookbehind-guarded) and `>[\s]*&`
// caught the standard `2>&1` log redirect (now only bare/wrongfd >& is
// blocked, `2>&1` passes). Escaped \$Names pass too; real substitution
// (unescaped $var, $(...), <( )>(, &) stays refused.
const SUBST_RE = /(?<!\\)(?:[`$]\(|[`]|[$][A-Za-z_{])|[<]\(|[>]\(|(?<!2)&[>]|(?<!2)>&/;

// ---------- reserved ports & ad-hoc server law ----------

// Refuses (a) ad-hoc file-server modules on any port, and (b) BIND/FORWARD
// commands that reference an owner-reserved port. READS are never refused:
// `curl http://127.0.0.1:8792/library.html`, `ss -ltnp`, `grep 8792` are
// legitimate diagnostics — only starting/forwarding listeners is the crime
// tonight's `python3 -m http.server 8792` impostor committed.
export function checkReservedPorts(cmd: string): string | null {
	const t = cmd.trim();
	// rule 1: ad-hoc file/server modules regardless of port
	if (/(?:^|\s)(?:-m\s+)?https?\.server\b|ftp\.server|socketserver/.test(t)) {
		return (
			"refused: ad-hoc file servers (http.server/ftp.server/socketserver) are banned — " +
			"the visual companion has its own start-server.sh, the knowledge library lives on :8792. " +
			"Never start a server by hand; use the proper tool and tell the owner the URL it prints."
		);
	}
	// rule 2: bind/forward intent + reserved port anywhere in the command
	const BIND_INTENT =
		/--port\b|\bPORT\s*=|^(?:nc|ncat|socat)\b|\bssh\b[^|;&]*\s-(?:L|R)\b|--listen\b/;
	if (BIND_INTENT.test(t)) {
		for (const p of Object.keys(RESERVED_PORTS)) {
			if (new RegExp("(?<!\\d)" + p + "(?!\\d)").test(t)) {
				return (
					"refused: port " + p + " is RESERVED for " + RESERVED_PORTS[p] +
					" — never bind, serve, proxy, or forward it from the bash lane. " +
					"Tell the owner which port you need and let them assign one."
				);
			}
		}
	}
	return null;
}

// ---------- per-segment checker ----------

// Shared tail policy for script runs (interpreter `bash X.sh` form AND the
// direct `/path/X.sh` exec form — same trust tier, same rules):
//   - script path must be absolute / ./ / ../
//   - script path itself must pass the folder law
//   - args: nothing, a confined redirect tail (> /tmp or /dev/null), or the
//     start-server flag whitelist — with --project-dir passing the folder law
// requireExecBit applies to the direct form: the file must actually be
// executable on disk, since the kernel will exec it without an interpreter.
function scriptTailOk(scriptPath: string, rest: string, requireExecBit: boolean): boolean {
	if (!(scriptPath.startsWith("/") || scriptPath.startsWith("./") || scriptPath.startsWith("../"))) {
		return false;
	}
	if (!lawCheck(scriptPath).ok) return false;
	if (requireExecBit) {
		try {
			fs.accessSync(scriptPath, fs.constants.X_OK);
			if (!fs.statSync(scriptPath).isFile()) return false;
		} catch {
			return false;
		}
	}
	const r = rest.trim();
	if (r === "" || r === "2>&1" ||
		/^(?:>|>>|2>|2>>)\s*(\/tmp\/\S+|\/dev\/null)(?:\s+2>&1)?$/.test(r)) {
		return lawCheckCmd(`${scriptPath} ${r}`) === null;
	}
	const allowedFlags =
		/^(?:--project-dir\s+\S+|--open|--host\s+\S+|--url-host\s+\S+|--foreground|--background|--idle-timeout-minutes\s+\d+)(?:\s+(?:--project-dir\s+\S+|--open|--host\s+\S+|--url-host\s+\S+|--foreground|--background|--idle-timeout-minutes\s+\d+))*$/;
	if (allowedFlags.test(r)) return lawCheckCmd(`${scriptPath} ${r}`) === null;
	return false;
}

export function checkSingle(c: string): string | null {
	const t = c.trim();
	if (!t) return "refused: empty command";
	if (/[\r\n]/.test(t)) return "refused: one single-line command per bash call — no multiline scripts";
	if (SUBST_RE.test(t)) {
		return "refused: shell substitution is not allowed (backticks, $(...), <(...), >(...), &, unescaped $var)";
	}
	const portErr = checkReservedPorts(t);
	if (portErr) return portErr;
	// 2026-11-10 owner (visual-companion loop analysis): the model's natural
	// output for script runs is the BARE full-path form —
	// `…/start-server.sh --project-dir …` — which previously landed in the
	// NEVER_RE net ("service" even matches inside "start-server.sh") and
	// looped the session. Direct exec of a full-path .sh is the same trust
	// tier as `bash <script.sh>`: one script, one command, confined args.
	const directRun = t.match(/^(\/\S+\.sh)\s*(.*)$/);
	if (directRun && scriptTailOk(directRun[1], directRun[2], true)) return null;
	if (NEVER_RE.test(t)) {
		// 2026-11-09 (owner's build-loop incident): `bash build-good-twin.sh`
		// was refused 15x and the model gave up and reported "done". Running
		// a PROJECT build script through an interpreter with NO extra
		// composition is a legitimate single command — allow it when the
		// arguments are file paths only.
		const scriptRun = t.match(/^(?:\/bin\/bash|\/bin\/sh|bash|sh)\s+(\S+\.sh)\s*(.*)$/);
		if (scriptRun && scriptTailOk(scriptRun[1], scriptRun[2], false)) {
			return null; // project build script via interpreter, confined args
		}
		return "refused: mutating, interpreter, shell or service-manager binary. To run a project build script: `bash <path/to/script.sh>` (or execute the script directly by its full path if it has the exec bit) with confined args. A redirect tail like `> /tmp/build.log 2>&1` is fine";
	}
	if (/^cd\b/.test(t)) {
		// 2026-11-10 owner order: cd is first-class now, subject to the
		// folder law like everything else (cd outside the anchor = ask).
		if (!/^cd\s+(\S+)$/.test(t)) return "refused: cd takes exactly one path argument";
		const target = t.replace(/^cd\s+/, "");
		const abs = target.startsWith("~") ? path.join(os.homedir(), target.slice(1)) : path.resolve(target);
		const check = lawCheck(abs);
		if (!check.ok) return check.reason;
		return null;
	}
	if (/^adb\b/.test(t)) {
		const toks2 = t.split(/\s+/);
		const sub = toks2[1] ?? "";
		if (!ADB_READ_SUBS.has(sub)) {
			return `refused: adb "${sub}" is not on the allowlist (read+install subs: devices, get-state, shell, logcat, bugreport, version, install, uninstall, push, pull)`;
		}
	}
	const toks = t.split(/\s+/);
	for (let i = 0; i < toks.length; i++) {
		const tok = toks[i];
		if (tok.startsWith("<")) {
			return "refused: input redirection is not allowed — pass the file path as an argument";
		}
		if (tok === ">" || tok === ">>" || tok === "2>" || tok === "2>>" || tok === "&>") {
			const target = toks[i + 1] ?? "";
			if (target !== "/dev/null" && !target.startsWith("/tmp/")) {
				return "refused: redirect target must be /dev/null or under /tmp/ (file writes go through file tools or /tmp/)";
			}
		}
	}
	if (t.includes(";")) {
		return "refused: semicolons are not allowed — one command per bash call";
	}
	for (const segRaw of t.split("|")) {
		const seg = segRaw.trim();
		if (!seg) {
			return "refused: empty pipeline segment";
		}
		const segToks = seg.split(/\s+/);
		const first = segToks[0].replace(/^["']|["']$/g, "");
		// 2026-11-09 (APK rebuild incident): the allowlist matched bare names
		// only, so javac/d8 — allowlisted on paper — were refused the moment
		// the model invoked them by full path, the only way they can be
		// invoked since they are not on PATH. Match by basename too.
		const base = first.split("/").pop() ?? first;
		if (!SAFE_BINS.has(first) && !SAFE_BINS.has(base)) {
			return `refused: "${first}" is not on the bash allowlist (${[...SAFE_BINS].sort().join(", ")}) — ask the operator for anything outside it`;
		}
		if (base === "tee") {
			// tee writes are confined like redirects (2026-11-09 regression wave)
			for (let j = 1; j < segToks.length; j++) {
				const t2 = segToks[j];
				if (t2.startsWith("-")) {
					continue;
				}
				if (t2 !== "/dev/null" && !t2.startsWith("/tmp/")) {
					return "refused: tee writes outside /tmp/ or /dev/null are not allowed — redirect to /tmp/ instead, or use the file tools";
				}
			}
			continue;
		}
		if (base === "git") {
			const sub = seg.split(/\s+/)[1];
			if (sub && !sub.startsWith("-") && !GIT_SAFE_SUB.has(sub)) {
				return `refused: git ${sub} is not on the read-only subcommand allowlist (${[...GIT_SAFE_SUB].sort().join(", ")})`;
			}
		}
	}
	// folder law on every path-ish token in the segment
	const lawErr = lawCheckCmd(t);
	if (lawErr) return lawErr;
	return null;
}

// ---------- top-level entry (&& chaining) ----------

export function checkCmd(cmd: string): string | null {
	const c = cmd.trim();
	if (!c || /[\r\n]/.test(c)) {
		return "refused: one single-line command per bash call — no multiline scripts";
	}
	// 2026-11-10 owner order: && chaining ALLOWED. Each && segment is
	// validated one by one as its own command; cd is a normal allowlisted
	// command (folder-law subject), not a special first-segment form.
	// 2026-11-11 (token-rate soak): || fallbacks are the same chaining law —
	// `ls -la X 2>/dev/null || echo "no apk"` mis-split on the bare-| rule
	// (the second | of || landed inside a split) and cost the live model
	// another refusal-retry class. Validate each || branch as its own command.
	if (c.includes("||")) {
		const alts = c.split("||");
		for (let s = 0; s < alts.length; s++) {
			const seg = alts[s].trim();
			if (!seg) return "refused: empty || branch";
			const err = checkCmd(seg);
			if (err) return `refused: || branch ${s + 1}: ${err}`;
		}
		return null;
	}
	if (c.includes("&&")) {
		const segs = c.split("&&");
		for (let s = 0; s < segs.length; s++) {
			const seg = segs[s].trim();
			if (!seg) return "refused: empty && segment";
			const err = checkSingle(seg);
			if (err) return `refused: && segment ${s + 1}: ${err}`;
		}
		return null;
	}
	return checkSingle(c);
}

// ---------- wiring ----------

export default function execGate(pi: ExtensionAPI): void {
	// Owner message → anchor/clear the folder law. message_end fires for every
	// message; only role === "user" with real text participates (the model's
	// own recaps and steer notes can NEVER set or clear the law).
	pi.on("message_end", (event: { message: { role?: string; content?: unknown } }) => {
		const msg = event.message as { role?: string; content?: unknown };
		if (msg?.role !== "user") return;
		const now = Date.now();
		const content =
			typeof msg.content === "string"
				? msg.content
				: Array.isArray(msg.content)
					? (msg.content as Array<{ type?: string; text?: string }>)
							.filter((c) => c?.type === "text")
							.map((c) => c.text ?? "")
							.join("\n")
					: "";
		if (!content.trim()) return;
		// identical text within 3s = delivery duplicate, not a new order
		if (content === lastOwnerText && now - lastOwnerTs < 3000) return;
		lastOwnerText = content;
		lastOwnerTs = now;
		if (/^\//.test(content.trim())) return; // slash command, not owner speech
		handleOwnerMessage(content);
	});

	// In-memory law mirrors the state file at boot.
	currentRoot = loadLaw();

	pi.on("tool_call", async (event: { toolName: string; input: Record<string, unknown> }) => {
		const root = currentRoot ?? loadLaw();
		// ---------- file tools under the law ----------
		if (root && (event.toolName === "read" || event.toolName === "edit" || event.toolName === "write")) {
			const p = String((event.input as { path?: unknown })?.path ?? "");
			if (p) {
				const abs = p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : path.resolve(p);
				const check = lawCheck(abs);
				if (!check.ok) return { block: true, reason: check.reason };
			}
		}
		if (event.toolName !== "bash" && event.toolName !== "shell") {
			return;
		}
		const reason = checkCmd(String((event.input as { command?: unknown })?.command ?? ""));
		if (reason) {
			return { block: true, reason };
		}
	});
}
