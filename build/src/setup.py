from setuptools import setup
from Cython.Build import cythonize
import numpy

setup(
    ext_modules = cythonize(
        ["app.py", "audit.py", "agent_run.py", "loop.py", "registry.py", "server.py", "splash.py", "wiring.py"],
        compiler_directives={'language_level': 3}
    ),
    zip_safe=False,
)
