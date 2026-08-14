#!/usr/bin/env python3
"""lib/prompt_queue.py — the default prompt-handling queue + conflict detector.

Every user prompt is decomposed into one or more agenda *items* and appended
to a persistent FIFO queue (the session's running task list). Future prompts
append after prior ones, so a multi-part request becomes a tracked agenda
across turns instead of a single blob the agent must juggle in its head.

Conflict detection (the user's explicit ask): when a new item contradicts an
item already on the queue, the submit is held and a question is surfaced:

    "earlier you said '<X>' but you just said '<Y>', and that conflicts.
     what do you want?"

so the user resolves the contradiction before it pollutes the agenda. A new
prompt that *revises* an earlier one ("actually", "instead", "no wait") is
treated as a supersession (the prior item is marked superseded), not a
conflict — changing your mind is allowed; contradicting yourself is not.

This is DEFAULT behavior: it is wired into ``hooks/user-prompt-submit.sh``,
which fires on every prompt. It is cheap (pure-Python heuristics, no LLM
call) and non-fatal (any error → the prompt passes through unqueued).

CLI (also exposed as ``cortexagent queue …``):
  python3 -m lib.prompt_queue submit --prompt "…"   # used by the hook
  python3 -m lib.prompt_queue list
  python3 -m lib.prompt_queue clear
  python3 -m lib.prompt_queue done <id>
  python3 -m lib.prompt_queue drop <id>
  python3 -m lib.prompt_queue context            # print compact agenda for injection

No Ollama, no hardcoded home paths (all via lib.config.CFG).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402

QUEUE_FILE = CFG.state_dir / "prompt_queue.json"

# ── Item / queue model ───────────────────────────────────────────────────────

class ItemStatus:
    QUEUED = "queued"
    ACTIVE = "active"
    DONE = "done"
    SUPERSEDED = "superseded"
    DROPPED = "dropped"


@dataclass
class Item:
    id: str
    text: str
    status: str = ItemStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    superseded_by: Optional[str] = None  # id of the item that replaced this one

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(id=d["id"], text=d["text"], status=d.get("status", ItemStatus.QUEUED),
                   created_at=float(d.get("created_at", 0.0) or 0.0),
                   superseded_by=d.get("superseded_by"))


def _load() -> list[Item]:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text())
        return [Item.from_dict(x) for x in data.get("items", [])]
    except Exception:
        return []


def _save(items: list[Item]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(
        {"items": [i.to_dict() for i in items], "updated_at": time.time()},
        indent=2))


def _next_id(items: list[Item]) -> str:
    n = 0
    for it in items:
        m = re.match(r"Q-(\d+)", it.id)
        if m:
            n = max(n, int(m.group(1)))
    return f"Q-{n + 1:03d}"


# ── Decomposition: multi-part prompt → items ────────────────────────────────

_NUM = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
_BUL = re.compile(r"^\s*[-*•·▪◦]\s+(.+)$")
_SEQ_WORDS = re.compile(
    r"\b(?:first|second|third|then|next|after that|afterwards|finally|lastly|"
    r"also|additionally|once that(?:'s)? done|when done)\b[:,]?\s*",
    re.IGNORECASE)


def decompose(prompt: str) -> list[str]:
    """Break a multi-part prompt into discrete agenda items.

    Strategy (in priority order — first hit wins):
      1. Numbered list lines  ("1. ... 2. ...")        → one item each
      2. Bulleted list lines  ("- ... * ...")          → one item each
      3. Sequential markers   ("first ... then ...")   → split on the markers
      4. Newline- or ;-joined imperatives that each start with a verb
         → one item each
      5. Otherwise            → the whole prompt is ONE item
         (don't over-split prose, questions, or single requests)

    Returns non-empty list of stripped item strings.
    """
    text = prompt.strip()
    if not text:
        return []

    # 1. Numbered list ("1. ... 2. ...") → one item each
    num_items = []
    for line in text.splitlines():
        m = _NUM.match(line)
        if m:
            num_items.append(m.group(2).strip())
    if len(num_items) >= 2:
        return num_items

    # 2. Bulleted list
    bul_items = []
    for line in text.splitlines():
        m = _BUL.match(line)
        if m:
            bul_items.append(m.group(1).strip())
    if len(bul_items) >= 2:
        return bul_items

    # 3. Sequential markers ("first do X, then do Y, finally do Z")
    if _SEQ_WORDS.search(text):
        # Split on the markers, keeping the text that follows each.
        parts = _SEQ_WORDS.split(text)
        parts = [p.strip().rstrip(",;.") for p in parts if p and p.strip()]
        # Drop a leading preamble before the first marker if it's just connective.
        if len(parts) >= 2:
            return parts

    # 4. Newline- or semicolon-joined imperatives (each starts with a verb)
    raw = re.split(r"\s*[\n;]+\s*", text)
    verbish = re.compile(r"^\w", re.UNICODE)  # any leading word; refined below
    imperative = re.compile(
        r"^(?:add|build|create|make|write|fix|update|change|remove|delete|rename|"
        r"move|copy|install|run|test|deploy|refactor|implement|set|configure|"
 r"enable|disable|start|stop|use|don't|do not|please|can you|could you|"
        r"check|verify|find|search|look|show|list|edit|replace|generate|setup)\b",
        re.IGNORECASE)
    imp_items = [p.strip() for p in raw if imperative.match(p.strip())]
    if len(imp_items) >= 2:
        return imp_items

    # 5. Single item
    return [text]


# ── Conflict detection ───────────────────────────────────────────────────────

# Directive = (verb, target, polarity, value). We extract a coarse signature
# per item and compare. This is heuristic by design — false negatives just mean
# a conflict slips through (the agent still has both items to reconcile); false
# positives would wrongly block, so we keep the rules conservative.

_VERB_POLARITY = {
    # positive / additive verbs
    "add": +1, "create": +1, "build": +1, "make": +1, "include": +1, "keep": +1,
    "enable": +1, "start": +1, "install": +1, "use": +1, "write": +1, "implement": +1,
    # negative / subtractive verbs
    "remove": -1, "delete": -1, "drop": +0, "disable": -1, "stop": -1, "exclude": -1,
    "hide": -1,
}

_NEGATION = re.compile(r"\b(?:don'?t|do not|never|no longer|stop|without)\b", re.IGNORECASE)
_REVISION = re.compile(
    r"^\s*(?:actually|instead|no\s+wait|never\s+mind|scratch\s+that|on\s+second\s+thought|"
    r"rather|change\s+(?:it|that|the)|update\s+(?:it|that|the)|forget\s+(?:it|that))\b",
    re.IGNORECASE)

# Tokens that must never be a directive *target*. The old heuristic took the
# word right after the verb, which is usually a stopword ("use the internet" →
# target "the") — so any two prompts that both start "use the…" / "keep the…"
# false-conflicted on "the". Skip these and land on the real noun.
_STOP_TARGET = {
    "the", "a", "an", "it", "them", "this", "that", "these", "those", "to", "for",
    "and", "or", "of", "in", "on", "at", "with", "from", "by", "my", "your", "our",
    "their", "its", "his", "her", "i", "you", "we", "they", "he", "she", "me", "us",
    "not", "dont", "don't", "do", "does", "did", "want", "wants", "need", "needs",
    "have", "has", "had", "is", "are", "was", "were", "be", "been", "being", "can",
    "could", "will", "would", "should", "shall", "may", "might", "must", "just",
    "only", "also", "then", "now", "here", "there", "all", "any", "some", "each",
    "every", "both", "either", "neither", "no", "yes", "ok", "okay", "please",
    "really", "actually", "still", "already", "yet", "so", "but", "if", "because",
    "when", "while", "after", "before", "up", "down", "out", "off", "over", "under",
    "again", "further", "once", "too", "very", "im", "youre", "that",
}

# "use/install <noun>" — same role, different choice → conflict
_ROLE_CHOICE = re.compile(
    r"\b(?:use|install|switch\s+to|go\s+with|adopt)\s+([A-Za-z0-9_.\-]+)", re.IGNORECASE)
# role = the noun after "for/as/to/in" (the thing the choice is FOR)
_ROLE = re.compile(r"\b(?:for|as|to|in)\s+(?:the\s+|a\s+|an\s+)?([A-Za-z0-9_.\-]+)", re.IGNORECASE)
# "rename X to Y" / "call it Y" — same subject, different new value
_RENAME = re.compile(
    r"\brename\s+(.+?)\s+to\s+(.+)$|call\s+(?:it|them|the\s+\S+)\s+(.+)$", re.IGNORECASE)


def _role_of(text: str) -> Optional[str]:
    m = _ROLE.search(text.lower())
    return m.group(1).lower() if m else None


def _directive(text: str) -> dict:
    """Extract a coarse directive signature from an item."""
    low = text.lower()
    words = re.findall(r"[A-Za-z']+", low)
    verb = None
    polarity = 0
    neg = False
    vi = -1
    for i, w in enumerate(words):
        if w in _VERB_POLARITY:
            verb = w
            vi = i
            # Negation only counts when it's ADJACENT to the verb (within 3
            # tokens). "i use the internet. i dont want to block it" must NOT
            # negate "use" just because "dont" appears later in the sentence —
            # that distant negation flipped polarity and false-conflicted.
            window = words[max(0, i - 3):i + 4]
            neg = any(_NEGATION.search(w2) for w2 in window)
            polarity = _VERB_POLARITY[w] * (-1 if neg else 1)
            break
    # target = first non-stopword after the verb ("use the internet" →
    # "internet", not "the" — stopword targets made unrelated prompts
    # false-conflict on "the").
    target = None
    if verb and vi >= 0:
        for w in words[vi + 1:]:
            if w not in _STOP_TARGET:
                target = w
                break
    role_choice = _ROLE_CHOICE.search(low)
    rename = _RENAME.search(low)
    return {
        "verb": verb,
        "target": target,
        "polarity": polarity,
        "negated": neg,
        "choice": role_choice.group(1).lower() if role_choice else None,
        "role": _role_of(text),
        "rename_subj": (rename.group(1) or "").strip().lower() if rename else None,
        "rename_val": (rename.group(2) or rename.group(3) or "").strip().lower() if rename else None,
    }


def _conflict_between(new_d: dict, new_text: str, old_d: dict, old_text: str) -> Optional[str]:
    """Return a human conflict reason if new contradicts old, else None."""
    # 1. Polarity flip on the same target ("use X" vs "don't use X",
    #    "enable X" vs "disable X", "keep X" vs "remove X").
    if (new_d["target"] and new_d["target"] == old_d["target"]
            and new_d["polarity"] and old_d["polarity"]
            and new_d["polarity"] != old_d["polarity"]):
        return (f"earlier you said '{old_text}' but you just said '{new_text}', "
                f"and that conflicts (opposite direction on '{new_d['target']}'). "
                f"what do you want?")

    # 2. Mutually-exclusive verbs on the same target (add vs remove, create vs delete).
    exclusive = {("add", "remove"), ("create", "delete"), ("start", "stop"),
                 ("enable", "disable"), ("include", "exclude")}
    if new_d["target"] and new_d["target"] == old_d["target"]:
        pair = tuple(sorted([new_d["verb"], old_d["verb"]]))
        if pair in exclusive:
            return (f"earlier you said '{old_text}' but you just said '{new_text}', "
                    f"and that conflicts ({pair[0]} vs {pair[1]} on '{new_d['target']}'). "
                    f"what do you want?")

    # 3. Same role, different choice ("use React for the frontend" vs "use Vue
    #    for the frontend"). Require a matching role so "use redis for caching"
    #    vs "use React for the frontend" do NOT false-fire.
    if (new_d["choice"] and old_d["choice"]
            and new_d["choice"] != old_d["choice"]
            and new_d["verb"] == old_d["verb"]
            and new_d["verb"] in ("use", "install", "switch", "go", "adopt")
            and new_d["role"] and old_d["role"]
            and (new_d["role"] == old_d["role"]
                 or new_d["role"] in old_d["role"] or old_d["role"] in new_d["role"])):
        return (f"earlier you said '{old_text}' but you just said '{new_text}', "
                f"and that conflicts (for '{new_d['role']}' you wanted "
                f"'{old_d['choice']}', now '{new_d['choice']}'). what do you want?")

    # 4. Rename the same thing to two different values.
    if (new_d["rename_subj"] and old_d["rename_subj"]
            and new_d["rename_subj"] == old_d["rename_subj"]
            and new_d["rename_val"] and old_d["rename_val"]
            and new_d["rename_val"] != old_d["rename_val"]):
        return (f"earlier you said '{old_text}' but you just said '{new_text}', "
                f"and that conflicts (rename '{new_d['rename_subj']}' to two "
                f"different values). what do you want?")

    return None


def _supersede_target(new_text: str, new_d: dict, live: list[Item]) -> Optional[Item]:
    """If new_text is a revision, find the prior live item it most likely replaces.

    Prefer a role match (e.g. both are "for the db") since a revision usually
    keeps the role and changes the choice. Fall back to shared significant
    tokens. Returns the Item or None.
    """
    role = new_d.get("role")
    # 1. Role match: same role, most recent.
    if role:
        for it in reversed(live):
            if _role_of(it.text) == role:
                return it
    # 2. Token overlap fallback.
    stop = {"the", "and", "but", "for", "that", "this", "with", "into", "from",
            "actually", "instead", "wait", "never", "mind", "scratch", "rather",
            "change", "update", "forget", "please", "use", "using", "now", "want"}
    new_tokens = {w.lower() for w in re.findall(r"[A-Za-z0-9_./\-]+", new_text)
                  if len(w) >= 2 and w.lower() not in stop}
    best, best_score = None, 0
    for it in reversed(live):
        toks = {w.lower() for w in re.findall(r"[A-Za-z0-9_./\-]+", it.text)
                if len(w) >= 2 and w.lower() not in stop}
        score = len(new_tokens & toks)
        if score > best_score:
            best, best_score = it, score
    return best if best_score >= 2 else None


# ── Submit (the core op used by the hook) ────────────────────────────────────

@dataclass
class SubmitResult:
    enqueued: list[Item]
    conflicts: list[str]        # human reasons (non-empty → submit held)
    superseded: list[str]       # ids of items marked superseded
    queue_size: int

    def to_dict(self) -> dict:
        return {
            "enqueued": [i.to_dict() for i in self.enqueued],
            "conflicts": self.conflicts,
            "superseded": self.superseded,
            "queue_size": self.queue_size,
        }


def submit(prompt: str) -> SubmitResult:
    """Decompose + enqueue a prompt. Holds conflicting items (does NOT persist them).

    On conflict: the non-conflicting new items ARE persisted; the conflicting
    ones are held out and ``conflicts`` lists the reasons. The caller (hook)
    surfaces the conflict as a blocking question.

    A revision ("actually …", "instead …") first marks the prior item it
    replaces as superseded and excludes it from conflict comparison — changing
    your mind is not a conflict. It can still conflict with a *different* live
    item.
    """
    items = _load()
    parts = decompose(prompt)
    if not parts:
        return SubmitResult([], [], [], len(items))

    is_revision = bool(_REVISION.match(prompt.strip()))

    # Live priors = items not done/superseded/dropped.
    live = [it for it in items
            if it.status not in (ItemStatus.DONE, ItemStatus.SUPERSEDED, ItemStatus.DROPPED)]

    # Revision → find + mark the supersede target FIRST, then exclude it from
    # conflict comparison so replacing an old choice isn't flagged as a conflict.
    superseded_ids: list[str] = []
    compare_set = live
    if is_revision and parts:
        first_d = _directive(parts[0])
        target = _supersede_target(parts[0], first_d, live)
        if target:
            target.status = ItemStatus.SUPERSEDED
            target.superseded_by = None  # filled in once we know the new id
            superseded_ids.append(target.id)
            compare_set = [it for it in live if it.id != target.id]

    # Compare each new part against the (reduced) live set; collect conflicts.
    new_items: list[Item] = []
    conflicts: list[str] = []
    for part in parts:
        new_d = _directive(part)
        conflict = None
        for old in compare_set:
            old_d = _directive(old.text)
            conflict = _conflict_between(new_d, part, old_d, old.text)
            if conflict:
                break
        if conflict:
            conflicts.append(conflict)
            continue  # hold this item out
        new_items.append(Item(id=_next_id(items + new_items), text=part))

    # Link the supersede target to the first enqueued new item (if any survived).
    if superseded_ids and new_items:
        for it in items:
            if it.id == superseded_ids[0]:
                it.superseded_by = new_items[0].id
                break

    # Persist: prior items (with any superseded updates) + the non-conflicting new items.
    items.extend(new_items)
    _save(items)

    return SubmitResult(new_items, conflicts, superseded_ids, len(items))


# ── Queue ops ────────────────────────────────────────────────────────────────

def list_items() -> list[Item]:
    return _load()


def clear() -> int:
    n = len(_load())
    _save([])
    return n


def mark_done(item_id: str) -> bool:
    items = _load()
    for it in items:
        if it.id == item_id:
            it.status = ItemStatus.DONE
            _save(items)
            return True
    return False


def drop(item_id: str) -> bool:
    items = _load()
    for it in items:
        if it.id == item_id:
            it.status = ItemStatus.DROPPED
            _save(items)
            return True
    return False


def agenda_context(max_items: int = 12) -> str:
    """Compact agenda string for injection into the agent's context."""
    items = _load()
    live = [it for it in items
            if it.status not in (ItemStatus.DONE, ItemStatus.SUPERSEDED, ItemStatus.DROPPED)]
    if not live:
        return ""
    done = sum(1 for it in items if it.status == ItemStatus.DONE)
    lines = [f"📋 Prompt queue — {len(live)} open / {done} done:"]
    for it in live[-max_items:]:
        tag = {"active": "▶", "queued": "·"}.get(it.status, "·")
        lines.append(f"  {tag} {it.id}: {it.text[:90]}")
    lines.append("Work the queue in order; mark items done with `cortexagent queue done <id>`.")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]

    if cmd == "submit":
        prompt = ""
        for i, a in enumerate(args):
            if a == "--prompt" and i + 1 < len(args):
                prompt = args[i + 1]
                break
            if a.startswith("--prompt="):
                prompt = a[len("--prompt="):]
                break
        if not prompt:
            print("usage: prompt_queue submit --prompt '...'", file=sys.stderr)
            return 2
        res = submit(prompt)
        _print_json(res.to_dict())
        return 0

    if cmd == "list":
        items = list_items()
        if not items:
            print("(queue empty)")
            return 0
        for it in items:
            icon = {"queued": "⏳", "active": "▶️", "done": "✅",
                    "superseded": "↩️", "dropped": "🗑️"}.get(it.status, "·")
            print(f"  {icon} {it.id} [{it.status}] {it.text[:80]}")
        return 0

    if cmd == "clear":
        n = clear()
        print(f"cleared {n} items")
        return 0

    if cmd == "done":
        if len(args) < 2:
            print("usage: prompt_queue done <id>", file=sys.stderr)
            return 2
        ok = mark_done(args[1])
        print("done" if ok else f"no such item: {args[1]}")
        return 0 if ok else 1

    if cmd == "drop":
        if len(args) < 2:
            print("usage: prompt_queue drop <id>", file=sys.stderr)
            return 2
        ok = drop(args[1])
        print("dropped" if ok else f"no such item: {args[1]}")
        return 0 if ok else 1

    if cmd == "context":
        ctx = agenda_context()
        if ctx:
            print(ctx)
        return 0

    print(f"unknown command: {cmd}\n", file=sys.stderr)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())