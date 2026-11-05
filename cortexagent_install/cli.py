"""cortexagent-setup — lay the CortexAgent app down, then run its own install.sh.

Deliberately small: no refactor of the app, no vendored copy of it, no
opinions about how it is configured. It fetches (or accepts) a checkout of
the project, verifies the checkout really is CortexAgent, and execs the
project's existing installer inside it — the same script a git clone user
would run by hand. Anything the installer does (config dir, memory dir,
native build, launcher symlink) is the project's own behavior, unchanged.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

DEFAULT_REPO = "https://github.com/greyok00/cortexagent.git"
DEFAULT_REF = "main"
INSTALLER = "install.sh"
MARKER = Path("engine") / "cli.py"


def default_dir() -> Path:
    """Where the app checkout lives: $CORTEXAGENT_SRC, else the XDG data dir."""
    env = os.environ.get("CORTEXAGENT_SRC")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "cortexagent" / "src"


def is_checkout(path: Path) -> bool:
    return (path / INSTALLER).is_file() and (path / MARKER).is_file()


def say(message: str) -> None:
    print(f"==> {message}", flush=True)


def need(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        sys.exit(f"cortexagent-setup: '{tool}' is required but was not found on PATH.")
    return found


def run(cmd: list[str], cwd: Path | None = None, dry: bool = False) -> int:
    printable = " ".join(str(c) for c in cmd)
    where = f"  (in {cwd})" if cwd else ""
    print(f"    $ {printable}{where}", flush=True)
    if dry:
        return 0
    return subprocess.call(cmd, cwd=str(cwd) if cwd else None)


def fetch(target: Path, repo: str, ref: str, update: bool, dry: bool) -> None:
    """Put a CortexAgent checkout at `target`, or explain why we won't."""
    if target.exists() and is_checkout(target):
        if (target / ".git").is_dir() and update:
            say(f"Updating existing checkout at {target}")
            git = need("git")
            # --ff-only: never rewrite whatever the user has locally.
            code = run([git, "pull", "--ff-only"], cwd=target, dry=dry)
            if code != 0:
                print(
                    "    NOTE: update skipped (local commits or no upstream). "
                    "Installing the checkout as-is.",
                    file=sys.stderr,
                )
        else:
            say(f"Using existing checkout at {target}")
        return

    if target.exists() and any(target.iterdir()):
        sys.exit(
            f"cortexagent-setup: {target} exists and is not a CortexAgent checkout.\n"
            "                    Refusing to touch it — pass --dir to choose another "
            "location."
        )

    git = need("git")
    say(f"Fetching CortexAgent ({ref}) into {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    shallow = [git, "clone", "--depth", "1", "--branch", ref, repo, str(target)]
    if run(shallow, dry=dry) == 0:
        return
    if dry:
        return

    # A raw commit SHA is not a valid --branch argument. Fall back to a full
    # clone plus checkout rather than guessing.
    print("    NOTE: shallow fetch of that ref failed — retrying as a full clone.", file=sys.stderr)
    if target.exists():
        shutil.rmtree(target)
    if run([git, "clone", repo, str(target)]) != 0:
        sys.exit("cortexagent-setup: git clone failed — nothing was installed.")
    if run([git, "-C", str(target), "checkout", ref]) != 0:
        sys.exit(f"cortexagent-setup: '{ref}' is not a branch, tag or commit in that repo.")


def confirm(target: Path, dry: bool, assume_yes: bool) -> None:
    print()
    say(f"About to run {target / INSTALLER}")
    print(
        "    It will install into your home directory: config, memory, a launcher\n"
        "    symlink in ~/.local/bin, and (on Linux) user systemd units. It does\n"
        "    not modify any other CortexAgent checkout you already have."
    )
    if dry or assume_yes:
        return
    if not sys.stdin.isatty():
        sys.exit("cortexagent-setup: no terminal to confirm on — re-run with --yes.")
    answer = input("    Continue? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        sys.exit("cortexagent-setup: cancelled — nothing was installed.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cortexagent-setup",
        description="Install CortexAgent: fetch the app, then run its own install.sh.",
        epilog=(
            "After it finishes, run 'cortexagent' to start a session. "
            "To undo: delete the checkout directory and ~/.local/bin/cortexagent."
        ),
    )
    parser.add_argument("--dir", metavar="PATH", type=Path, default=None,
                        help="where to put the checkout "
                             "(default: $CORTEXAGENT_SRC, else ~/.local/share/cortexagent/src)")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help="git remote to fetch from (default: %(default)s)")
    parser.add_argument("--ref", default=DEFAULT_REF,
                        help="branch, tag or commit to install (default: %(default)s)")
    parser.add_argument("--from", dest="local", metavar="PATH", type=Path, default=None,
                        help="install from a checkout you already have, offline")
    parser.add_argument("--no-update", action="store_true",
                        help="never 'git pull' an existing checkout")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands without running anything")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    parser.add_argument("--print-dir", action="store_true",
                        help="print the resolved checkout path and exit")
    parser.add_argument("--version", action="version", version=f"cortexagent-setup {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = Path(args.local).expanduser().resolve() if args.local else Path(args.dir or default_dir()).expanduser()

    if args.print_dir:
        print(target)
        return 0

    need("python3")

    if args.local:
        if not is_checkout(target):
            sys.exit(
                f"cortexagent-setup: {target} is not a CortexAgent checkout "
                f"(no {INSTALLER} + {MARKER})."
            )
        say(f"Using your local checkout at {target}")
        print(
            "    NOTE: the project's installer minifies source in place, so that\n"
            "    checkout will be edited. Use a throwaway clone if that matters."
        )
    else:
        fetch(target, args.repo, args.ref, update=not args.no_update, dry=args.dry_run)

    if not args.dry_run and not is_checkout(target):
        sys.exit(f"cortexagent-setup: {target} still is not a CortexAgent checkout — stopping.")

    confirm(target, dry=args.dry_run, assume_yes=args.yes)

    print()
    code = run(["bash", INSTALLER], cwd=target, dry=args.dry_run)
    if code != 0:
        print(f"\ncortexagent-setup: {INSTALLER} exited {code}.", file=sys.stderr)
        return code

    if not args.dry_run:
        print()
        say("CortexAgent is installed.")
        print(f"    checkout: {target}")
        print("    start it: cortexagent          # interactive session")
        print("              cortexagent -p \"fix this bug\"")
        print("    if 'cortexagent' is not found, add ~/.local/bin to PATH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
