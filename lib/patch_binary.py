#!/usr/bin/env python3
"""patch_binary.py — Patch the Claude Code binary.

Suppresses the "Tips" and "What's new" sections in the welcome banner AND
rebrands the persistent header text "Claude Code v<ver>" → "CortexAgent
v<ver>" (same-length in-place swap, so the sparkle logo graphic remains).
The wrapper script (bin/cortexagent) handles the rest of the visual identity
(wolf banner, terminal title).

Usage:
  python3 lib/patch_binary.py              # Patch the installed claude binary
  python3 lib/patch_binary.py --check      # Check if already patched
  python3 lib/patch_binary.py --restore    # Restore from backup
"""
import os
import sys
import shutil
from pathlib import Path

NVM_ROOT = Path.home() / ".nvm"
NODE_VERSIONS = sorted(
    (NVM_ROOT / "versions" / "node").glob("*/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
) if (NVM_ROOT / "versions" / "node").exists() else []

CANDIDATES = list(NODE_VERSIONS) + [
    Path("/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
    Path("/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
]

CLAUDE_BIN = None
for c in CANDIDATES:
    if c.exists():
        CLAUDE_BIN = c
        break

if not CLAUDE_BIN:
    import subprocess
    try:
        result = subprocess.run(["which", "claude"], capture_output=True, text=True)
        if result.returncode == 0:
            path = Path(result.stdout.strip())
            if path.is_symlink():
                path = Path(os.readlink(str(path)))
                if not path.is_absolute():
                    path = path.parent / path
            CLAUDE_BIN = path
    except:
        pass

if not CLAUDE_BIN:
    print("Could not find claude binary", file=sys.stderr)
    sys.exit(1)

BACKUP_PATH = CLAUDE_BIN.with_suffix(".exe.bak")

REPLACEMENTS = [
    # Suppress the entire Claude welcome banner
    ("Welcome to Claude Code", "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    ("Welcome back!", "\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    ("Run /init to create a CLAUDE.md file with instructions for Claude", "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    ("Tips for getting started", "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    ("What's new", "\0\0\0\0\0\0\0\0\0\0"),
    ("Bug fixes and improvements", "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    ("release-notes", "\0\0\0\0\0\0\0\0\0\0\0\0\0"),
    # ── Rebrand two "Claude Code v<ver>" display strings → "CortexAgent v<ver>"
    # SAME-LENGTH in-place swap (11→11 chars) — no binary offset / checksum risk.
    # NOTE: these two literals (count=1 each) are the web-UI header template
    # (<span>CortexAgent v${Ks(e.claudeVersion)}</span>) and a null-terminated
    # string-table entry — NOT the terminal/TUI persistent header. The locked
    # TUI header renders "Claude" / "Code" / "v"+version as separate
    # cursor-positioned fragments with the sparkle logo assembled per-char;
    # none of those is a safely patchable contiguous string, and "Code"→
    # "Agent" is an unsafe 4→5 length change. So the TUI header text is left
    # as Claude's; the web-UI header + title + statusLine + wolf banner carry
    # the CortexAgent identity. The 13 functional "Claude Code version …"
    # managed-settings docs are left intact (they end in "\x00"/"${…}", not
    # "ersion"). Same binary is shared with the ollama-launched claude agent,
    # but the terminal render of both is unaffected by these two swaps.
    ("Claude Code v\x00", "CortexAgent v\x00"),
    ("Claude Code v${Ks(e.claudeVersion)}", "CortexAgent v${Ks(e.claudeVersion)}"),
]


def patch_binary():
    if not CLAUDE_BIN.exists():
        print(f"Binary not found: {CLAUDE_BIN}", file=sys.stderr)
        return False

    if not BACKUP_PATH.exists():
        print(f"Creating backup: {BACKUP_PATH}")
        shutil.copy2(CLAUDE_BIN, BACKUP_PATH)

    data = bytearray(CLAUDE_BIN.read_bytes())
    patched = 0

    for old, new in REPLACEMENTS:
        old_bytes = old.encode("utf-8")
        new_bytes = new.encode("utf-8")

        if len(new_bytes) > len(old_bytes):
            continue

        padded = new_bytes + b"\x00" * (len(old_bytes) - len(new_bytes))

        idx = 0
        count = 0
        while True:
            idx = data.find(old_bytes, idx)
            if idx == -1:
                break
            data[idx:idx + len(old_bytes)] = padded
            idx += len(old_bytes)
            count += 1
            patched += 1

    tmp = CLAUDE_BIN.with_suffix(".exe.patch")
    tmp.write_bytes(bytes(data))
    os.chmod(tmp, 0o755)
    tmp.replace(CLAUDE_BIN)

    print(f"Patched {patched} strings in {CLAUDE_BIN}")
    return True


def check_patched():
    if not CLAUDE_BIN.exists():
        print(f"Binary not found: {CLAUDE_BIN}")
        return
    data = CLAUDE_BIN.read_bytes()
    patched = 0
    original = 0
    for old, new in REPLACEMENTS:
        old_bytes = old.encode("utf-8")
        new_bytes = new.encode("utf-8")
        if old_bytes in data:
            original += 1
        if new_bytes.rstrip(b"\x00") in data:
            patched += 1
    print(f"Binary: {CLAUDE_BIN}")
    print(f"Size: {len(data):,} bytes")
    print(f"Original strings found: {original}")
    print(f"Patched strings found: {patched}")
    if original == 0 and patched > 0:
        print("Status: PATCHED")
    elif original > 0:
        print("Status: NOT PATCHED")
    else:
        print("Status: UNKNOWN")


def restore_backup():
    if not BACKUP_PATH.exists():
        print(f"No backup found: {BACKUP_PATH}")
        return False
    print(f"Restoring from: {BACKUP_PATH}")
    shutil.copy2(BACKUP_PATH, CLAUDE_BIN)
    os.chmod(CLAUDE_BIN, 0o755)
    print(f"Restored: {CLAUDE_BIN}")
    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_patched()
    elif "--restore" in sys.argv:
        restore_backup()
    else:
        patch_binary()
