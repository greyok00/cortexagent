// cortex/packages/coding-agent/src/core/cold-memory.ts
//
// Cold-memory recall. Surfaces relevant entries from THIS agent's
// cold store (env CORTEXAGENT_MEMORY_DIR → default ~/.cortexagent/memory/cold/)
// into the system prompt so the local
// model can answer with verbatim facts instead of inventing them.
//
// Lookup is keyword-based: the agent's last user prompt is scored against
// the cold-memory "topic" field (or first ~80 chars of body when there's
// no topic) and the top N matches are injected under a `<cold_memory>`
// block. The block is sized to stay cheap — typically 200–800 tokens per
// entry, capped at 3 entries by default.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
const env = process.env;
// 2026-10-14 (local port): the local agent reads ITS OWN store — never the
// legacy cortexllm path.
const COLD_DIR = env.CORTEXAGENT_MEMORY_DIR
    ? join(env.CORTEXAGENT_MEMORY_DIR, "cold")
    : join(homedir(), ".cortex-agent", "memory", "cold");
let cache = null;
const CACHE_TTL_MS = 30_000;
function loadColdDir() {
    try {
        if (!readdirSync(COLD_DIR))
            return [];
    }
    catch {
        return [];
    }
    const out = [];
    for (const f of readdirSync(COLD_DIR)) {
        const fp = join(COLD_DIR, f);
        try {
            const st = statSync(fp);
            if (!st.isFile())
                continue;
            const raw = readFileSync(fp, "utf-8");
            const body = stripFrontmatter(raw);
            const topic = extractTopic(body) ?? stripExt(f);
            out.push({ id: f, topic, body: body.slice(0, 4000), ts: st.mtimeMs });
        }
        catch {
            /* ignore unreadable entries */
        }
    }
    out.sort((a, b) => b.ts - a.ts);
    return out;
}
function stripFrontmatter(s) {
    // Drop leading `--- ... ---` so YAML frontmatter doesn't pollute the body
    const m = s.match(/^---\n[\s\S]*?\n---\n?/);
    return m ? s.slice(m[0].length) : s;
}
function extractTopic(body) {
    // First markdown heading, or first non-empty line if no heading.
    const heading = body.match(/^#+\s+(.+)$/m);
    if (heading)
        return heading[1].trim();
    const first = body.split("\n").find((l) => l.trim().length > 0);
    return first ? first.trim().slice(0, 80) : null;
}
function stripExt(name) {
    return name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
}
function getEntries() {
    const now = Date.now();
    if (cache && now - cache.at < CACHE_TTL_MS)
        return cache.entries;
    const entries = loadColdDir();
    cache = { entries, at: now };
    return entries;
}
export function recallColdMemory(opts = {}) {
    const { prompt = "", limit = 3, maxCharsPerEntry = 4000 } = opts;
    const entries = getEntries();
    if (entries.length === 0) {
        return { entries: [], formatted: "", tokens: 0 };
    }
    const keywords = tokenize(prompt);
    const scored = entries
        .map((e) => ({ entry: e, score: scoreEntry(e, keywords) }))
        .sort((a, b) => b.score - a.score || b.entry.ts - a.entry.ts);
    const chosen = scored.slice(0, limit).filter((s) => s.score > 0 || keywords.length === 0);
    if (chosen.length === 0) {
        return { entries: [], formatted: "", tokens: 0 };
    }
    const formatted = "\n<cold_memory>\n" +
        "These notes are pre-cached facts the user maintains. Prefer them\n" +
        "over invented answers. If a fact contradicts your training data,\n" +
        "trust the cold-memory entry — it's current.\n\n" +
        chosen
            .map(({ entry }, i) => {
            const body = entry.body.length > maxCharsPerEntry
                ? entry.body.slice(0, maxCharsPerEntry) + "\n…(truncated)"
                : entry.body;
            return `<memory id="${entry.id}" topic="${escapeXml(entry.topic)}">\n${body}\n</memory>`;
        })
            .join("\n\n") +
        "\n</cold_memory>\n";
    const tokens = Math.ceil(formatted.length / 4);
    return {
        entries: chosen.map((c) => c.entry),
        formatted,
        tokens,
    };
}
function tokenize(s) {
    return s
        .toLowerCase()
        .replace(/[^a-z0-9_\s-]+/g, " ")
        .split(/\s+/)
        .filter((t) => t.length >= 3 && !STOP.has(t));
}
const STOP = new Set([
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "any",
    "can",
    "had",
    "her",
    "was",
    "one",
    "our",
    "out",
    "day",
    "get",
    "has",
    "him",
    "his",
    "how",
    "its",
    "may",
    "new",
    "now",
    "old",
    "see",
    "two",
    "way",
    "who",
    "boy",
    "did",
    "use",
    "her",
    "what",
    "when",
    "your",
    "from",
    "this",
    "that",
    "with",
    "have",
    "will",
    "would",
    "could",
    "should",
    "about",
    "there",
    "their",
    "which",
    "these",
    "those",
    "into",
    "than",
]);
function scoreEntry(e, keywords) {
    if (keywords.length === 0)
        return 1;
    const haystack = (e.topic + " " + e.body).toLowerCase();
    let score = 0;
    for (const kw of keywords) {
        const re = new RegExp(`\\b${kw}\\b`, "g");
        const matches = haystack.match(re);
        if (matches)
            score += matches.length;
    }
    return score;
}
function escapeXml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
//# sourceMappingURL=cold-memory.js.map