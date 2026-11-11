from setuptools import setup
from Cython.Build import cythonize
setup(ext_modules=cythonize([r'"${HOME}/cortex-agent"/mcp/src/memory/db.py', r'"${HOME}/cortex-agent"/mcp/src/memory/memory.py'], compiler_directives={'language_level': '3', 'annotation_typing': False}), zip_safe=False)
