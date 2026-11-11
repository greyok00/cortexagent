from setuptools import setup
from Cython.Build import cythonize
setup(ext_modules=cythonize([r'"${HOME}/cortex-agent"/mcp/src/research/keys.py', r'"${HOME}/cortex-agent"/mcp/src/research/page_builder.py', r'"${HOME}/cortex-agent"/mcp/src/research/pipeline.py', r'"${HOME}/cortex-agent"/mcp/src/research/research.py'], compiler_directives={'language_level': '3', 'annotation_typing': False}), zip_safe=False)
