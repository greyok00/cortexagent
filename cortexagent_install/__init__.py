"""Installer for CortexAgent.

This package ships no application code. CortexAgent is a source-run project:
its launcher, daemon and Cython accelerators all assume they live inside a
stable checkout, so this package's only job is to put that checkout in place
and hand off to the project's own ``install.sh``.
"""

__version__ = "0.7.9"
__all__ = ["__version__"]
