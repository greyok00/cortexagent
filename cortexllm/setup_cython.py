#!/usr/bin/env python3
"""setup_cython.py — Build Cython extensions for CPU-bound hot paths.

Compiles .pyx files into .so shared objects for:
  1. cortex_tokenizer — BM25 tokenization (expected 2-3x speedup)
  2. cortex_graph — Graph traversal (BFS/DFS, expected 2-4x speedup)

Usage:
  python3 setup_cython.py build     # Build all extensions
  python3 setup_cython.py build --clean  # Clean and rebuild
  python3 setup_cython.py status    # Check compilation status
  python3 setup_cython.py test      # Build + test all extensions
  python3 setup_cython.py benchmark  # Benchmark Cython vs Python
"""
from __future__ import annotations

import os
import sys
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CYTHON_DIR = REPO_ROOT / "cortexllm"
PY_FILES = list(CYTHON_DIR.glob("*.pyx"))
SO_FILES = list(CYTHON_DIR.glob("*.so"))


def build_all(clean: bool = False) -> int:
    """Build all Cython extensions."""
    if clean:
        _clean()
    
    # Check for Cython
    try:
        import Cython
        print(f"Cython version: {Cython.__version__}")
    except ImportError:
        print("Installing Cython...")
        subprocess.run([sys.executable, "-m", "pip", "install", "cython"], check=True)
        import Cython
        print(f"Cython version: {Cython.__version__}")
    
    from Cython.Build import cythonize
    
    for pyx_file in PY_FILES:
        print(f"Building {pyx_file.name}...")
        try:
            cythonize([pyx_file], compiler_directives={
                'language_level': "3",
                'boundscheck': False,
                'cdivision': True,
                'always_nonnegative': True,
            })
            # Build the extension
            result = subprocess.run(
                [sys.executable, "-m", "setuptools.build_ext", "--inplace"],
                cwd=str(CYTHON_DIR),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"  ⚠️  Build failed for {pyx_file.name}: {result.stderr[:200]}")
                print(f"  (This is OK if Cython is not available — pure Python fallback is used)")
            else:
                print(f"  ✅ Built {pyx_file.name}.so")
        except Exception as e:
            print(f"  ⚠️  Failed to build {pyx_file.name}: {e}")
    
    print("\nBuild complete.")
    return 0


def _clean():
    """Clean build artifacts."""
    for f in SO_FILES:
        f.unlink(missing_ok=True)
    # Clean compiled .pyc files
    for f in CYTHON_DIR.rglob("*.pyc"):
        f.unlink(missing_ok=True)
    print("Cleaned build artifacts.")


def status() -> int:
    """Check compilation status."""
    print("Cython extension status:")
    for pyx in sorted(CYTHON_DIR.glob("*.pyx")):
        so = pyx.with_suffix(".so")
        if so.exists():
            size = so.stat().st_size
            mtime = so.stat().st_mtime
            print(f"  {pyx.name}.so  {size:,} bytes  (compiled)")
        else:
            print(f"  {pyx.name}.so  not compiled  (pure Python fallback active)")
    return 0


def test() -> int:
    """Build and test all extensions."""
    print("Building Cython extensions...")
    build_all(clean=True)
    
    print("\nRunning tests...")
    for pyx in sorted(CYTHON_DIR.glob("*.pyx")):
        print(f"\nTesting {pyx.name}...")
        try:
            module_name = pyx.stem
            result = subprocess.run(
                [sys.executable, str(pyx), "--smoke"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            print(result.stdout.strip())
            if result.returncode != 0:
                print(f"  stderr: {result.stderr[:200]}")
        except Exception as e:
            print(f"  Test failed: {e}")
    
    return 0


def benchmark() -> int:
    """Benchmark Cython vs Python for tokenization."""
    test_text = (
        "CortexAgent is a local AI agent system that uses llama-server "
        "for model inference, SQLite for memory storage, and Python for "
        "tool execution. The system supports multiple memory tiers, graph "
        "extraction, and ontology management. Python tokenization benchmarks "
        "show that Cython can provide 2-3x speedup for CPU-bound text processing."
    )
    
    print(f"Benchmark text ({len(test_text)} chars): {test_text[:80]}...")
    
    # Benchmark pure Python
    from cortexllm.cortex_tokenizer import tokenize_py, count_tokens_py
    import timeit
    
    py_time = timeit.timeit(
        lambda: tokenize_py(test_text),
        number=1000,
        globals=globals(),
    )
    
    print(f"\nPure Python tokenize: {py_time:.3f}s for 1000 calls")
    print(f"  → {py_time * 1000:.1f}ms per call")
    
    # Try Cython version
    try:
        from cortexllm.cortex_tokenizer import tokenize, count_tokens
        cy_time = timeit.timeit(
            lambda: tokenize(test_text),
            number=1000,
            globals=globals(),
        )
        print(f"\nCython tokenize:      {cy_time:.3f}s for 1000 calls")
        print(f"  → {cy_time * 1000:.1f}ms per call")
        print(f"\nSpeedup: {py_time / cy_time:.1f}x")
    except Exception as e:
        print(f"\nCython not available: {e}")
        print("  (Build with: python3 setup_cython.py build)")
    
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    
    cmd = sys.argv[1]
    if cmd == "build":
        clean = "--clean" in sys.argv
        return build_all(clean=clean)
    if cmd == "status":
        return status()
    if cmd == "test":
        return test()
    if cmd == "benchmark":
        return benchmark()
    
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
