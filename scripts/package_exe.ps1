# package_exe.ps1 — Windows packaging placeholder (owner: "future placeholder";
# 2026-10-24 master prompt: not a priority, document the path).
#
# Planned shape (when Windows shipping becomes real):
#   1. A Windows the engine build compiled as cortexagent-server.exe with the same
#      vendored-lib layout (rpath equivalent = DLLs adjacent, LoadLibrary $EXEDIR).
#   2. The Cython .so set rebuilt for win-amd64 (python 3.13 windows x64;
#      the .py sources needed -> keep sources per-module in build/src during
#      the cross-compile, ship only executables).
#   3. Node TUI dist unchanged (cross-platform .js) + bundled node.exe.
#   4. PyInstaller-style bootstrap: cortexagent.exe -> the same launcher order
#      (mask env -> verify -> lane -> VRAM -> model async -> TUI).
#   5. NSIS or MSIX installer writing /Program Files/cortexagent + %APPDATA%/
#      cortexagent/agent config; port_policy.json unchanged (ports are 6666+).
#
# NOT to be run today. Keep this file as the documented path so a future
# session executes exactly this plan instead of inventing one.
Write-Host "cortexagent Windows packaging: placeholder only - see comments in this file." -ForegroundColor Yellow