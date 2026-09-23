#!/usr/bin/env python3
import json, subprocess, urllib.request

CHECKS = [
    ("responderd", "the security auto-responder", "user"),
    ("fail2ban", "the login-failure blocker", "system"),
    ("tetragon", "the system-activity watcher", "system"),
    ("clamav-daemon", "the antivirus scanner", "system"),
]

def svc(name, scope="user"):
    cmd = (["systemctl", "--user", "is-active", name] if scope == "user"
           else ["systemctl", "is-active", name])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() == "active"

def model():
    try:
        urllib.request.urlopen("http://127.0.0.1:11436/metrics", timeout=4)
        return "the local AI lane is up"
    except Exception:
        return "the local AI lane is DOWN"

def gpu():
    try:
        out = subprocess.run(["/usr/bin/nvidia-smi", "-q", "-d", "POWER"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "Current Power Limit" in line:
                w = int(float(line.split(":")[1].strip().split()[0]))
                if w < 80:
                    return f"the GPU is power-capped at {w}W (should be 90W)"
        return "the GPU is at full power (90W)"
    except Exception:
        return "GPU status unknown"

if __name__ == "__main__":
    lines = []
    for unit in CHECKS:
        name, human = unit[0], unit[1]
        scope = unit[2] if len(unit) > 2 else "user"
        lines.append(f"{'OK' if svc(name, scope) else 'DOWN'}: {human}")
    lines.append(f"{'OK' if model().startswith('the local AI is up') else 'DOWN'}: "
                 + (model() if model() == "the local AI is up" else model()))
    lines.append(gpu())
    print(" | ".join(lines))
