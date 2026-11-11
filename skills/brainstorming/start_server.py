#!/usr/bin/env python3
import subprocess, os, json, time

os.chdir('/home/grey/.cortex-agent/agent/skills/brainstorming')
proc = subprocess.Popen(['/home/grey/.nvm/versions/node/v22.22.2/bin/node', 'scripts/server.cjs'])
print('Started node server, pid:', proc.pid)

time.sleep(3)
proc.poll()
if proc.returncode is None:
    print('Server is alive')
else:
    print('Server exited')
