import sys
from pathlib import Path

ROOT = Path(""${HOME}/cortex-agent"")
sys.path.insert(0, str(ROOT))

from ui.app import main

main()
