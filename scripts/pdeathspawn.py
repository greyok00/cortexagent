import ctypes
import os
import signal
import sys

if len(sys.argv) < 2:
    sys.exit(2)
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl(1, signal.SIGKILL, 0, 0, 0)
if os.getppid() == 1:
    sys.exit(1)
os.execvp(sys.argv[1], sys.argv[1:])