#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MODULES = (
    "lib/charts.py",
    "lib/coding_practices.py",
    "lib/cold_distiller.py",
    "lib/domain_db.py",
    "lib/token_tracker.py",
)

_DIRECTIVES = {
    "language_level": 3,
    "boundscheck": False,
    "cdivision": True,
    "initializedcheck": False,
    "nonecheck": False,
}

def _so_for(src: Path) -> Path:
    import sysconfig
    ext = sysconfig.get_config_var("EXT_SUFFIX")
    return src.with_suffix(ext)

def _stale(src: Path) -> bool:
    so = _so_for(src)
    return not so.exists() or src.stat().st_mtime > so.stat().st_mtime

def _toolchain_ok() -> bool:
    try:
        import Cython
    except Exception:
        return False
    return shutil_which("gcc") is not None or shutil_which("cc") is not None

def shutil_which(name: str):
    import shutil
    return shutil.which(name)

def _build() -> int:
    if not _toolchain_ok():
        print("⚠  build_opt: Cython or a C compiler not found — using .py sources (fine).")
        return 0
    from setuptools import Distribution, Extension
    from setuptools.command.build_ext import build_ext
    from Cython.Build import cythonize

    stale = [m for m in MODULES if _stale(REPO / m)]
    if not stale:
        print("build_opt: all modules already compiled — nothing to do.")
        return 0

    exts = cythonize(
        [
            Extension(
                m.replace("/", ".").replace(".py", ""),
                [str(REPO / m)],
            )
            for m in stale
        ],
        compiler_directives=_DIRECTIVES,
        quiet=True,
    )
    cmd = build_ext(Distribution({"ext_modules": exts}))
    cmd.inplace = True
    cmd.ensure_finalized()
    if cmd.compiler is None:
        cmd.compiler = "unix"
    cmd.run()
    for m in stale:
        (REPO / m).with_suffix(".c").unlink(missing_ok=True)
        print(f"  compiled {m} → {_so_for(REPO / m).name}")
    import shutil
    shutil.rmtree(REPO / "build", ignore_errors=True)
    return 0

def _check() -> int:
    built, py = [], []
    for m in MODULES:
        (built if _so_for(REPO / m).exists() else py).append(m)
    print(f"build_opt: {len(built)} compiled ({', '.join(p.replace('lib/', '') for p in built) or 'none'})")
    if py:
        print(f"           {len(py)} on .py fallback ({', '.join(p.replace('lib/', '') for p in py)})")
    return 0

def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--check" in argv:
        return _check()
    return _build()

if __name__ == "__main__":
    sys.exit(main())
