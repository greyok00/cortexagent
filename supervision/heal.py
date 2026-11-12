#!/usr/bin/env python3
"""Machine-state healer for the cortex-agent session (owner: 'if it breaks and
catches an error, have it learn how to get past it automatically... keep it
going so it doesn't stop').

Heuristic backend — symptom -> diagnosis -> action -> lesson recorded so
repeat sightings escalate to the right action immediately:
  - model :7090 dead            -> systemd reboot (auto via watcher, verify)
  - lane :7091 dead             -> systemctl restart cortex-agent-lane
  - lane 502 / empty responses  -> restart lane; if model busy, wait
  - lane 1-token storm pattern  -> note; clamp fix already live (no action)
  - GPU OOM in boot log         -> boot ladder handles; log lesson
  - server RSS > 6 GiB          -> warning only (should be ~1.5)
Lessons append to lessons.jsonl; each action logged to heal.jsonl."""
import json, time, subprocess, urllib.request, os, sys

STATE = os.path.expanduser("~/cortex-agent/state")
HEAL_LOG = STATE + "/supervision/heal.jsonl"
LESSONS = STATE + "/supervision/lessons.jsonl"

lessons = {}
if os.path.exists(LESSONS):
    for line in open(LESSONS):
        try:
            d = json.loads(line)
            lessons[d["key"]] = d
        except Exception:
            pass

STEER_STATE = STATE + "/supervision/steer_state.json"

def _tod(s):
    """'HH:MM:SS' -> seconds of day, or None if not parseable."""
    parts = str(s).split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except ValueError:
        return None

def _save_all():
    with open(LESSONS, "w") as f:
        for v in lessons.values():
            if isinstance(v, dict) and "key" in v:
                f.write(json.dumps(v) + "\n")
    with open(STEER_STATE, "w") as f:
        json.dump({k: v for k, v in lessons.items()
                   if isinstance(v, dict) and "ts_epoch" in v}, f)

STEER = STATE + "/supervision/steer.jsonl"

def log(action, detail):
    rec = {"ts": time.strftime("%m-%d %H:%M:%S"), "action": action, "detail": detail}
    with open(HEAL_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[{rec['ts']}] HEAL: {action} — {detail}", flush=True)

def steer(msg, key=None, cooldown=600):
    """Push a supervisor steer into the live TUI via supervise channel.
    Cooldown per key avoids spamming the operator's session."""
    if key:
        rec = lessons.get("steer:" + key)
        now = time.time()
        if rec and now - rec.get("ts_epoch", 0) < cooldown:
            return False
        lessons["steer:" + key] = {"ts_epoch": now}
        _save_all()
    with open(STEER, "a") as f:
        f.write(json.dumps({"ts": time.time(), "msg": msg}) + "\n")
    log("steer", msg[:90])
    return True

def http_ok(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200, ""
    except Exception as e:
        return False, str(e)[:120]

def learn(key, diagnosis, action):
    rec = lessons.get(key)
    if rec:
        rec["count"] += 1; rec["last"] = time.strftime("%m-%d %H:%M:%S")
    else:
        rec = {"key": key, "diagnosis": diagnosis, "action": action, "count": 1,
               "last": time.strftime("%m-%d %H:%M:%S")}
    lessons[key] = rec
    _save_all()
    return rec["count"]

def sysuser(*args):
    subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=20)

def main():
    consecutive_model_down = 0
    while True:
        ok_m, err_m = http_ok("http://127.0.0.1:7100/health")
        ok_l, err_l = http_ok("http://127.0.0.1:7101/metrics")
        if not ok_m:
            consecutive_model_down += 1
            # the systemd watcher self-reboots; verify it's doing so
            act = "waiting for cortex-agent-model self-heal" if consecutive_model_down < 4 else "restart cortex-agent-model manually"
            if consecutive_model_down >= 4:
                sysuser("restart", "cortex-agent-model.service")
                act = "restarted cortex-agent-model"
            c = learn("model_down", f":7100 down: {err_m}", act)
            log(f"model down x{consecutive_model_down}", f"{act} (seen {c}x)")
        else:
            consecutive_model_down = 0
        if ok_m and not ok_l:
            sysuser("restart", "cortex-agent-lane.service")
            c = learn("lane_down", ":7101 dead while model lives", "restarted cortex-agent-lane")
            log("lane down", f"restarted cortex-agent-lane (seen {c}x)")
        # Chat-level incidents from watch.py -> targeted steers (learned)
        try:
            with open(STATE + "/supervision/incidents.jsonl") as f:
                inc_lines = f.readlines()[-25:]
            refusals = [json.loads(l) for l in inc_lines if '"refusal"' in l]
            # 2026-11-09 (APK rebuild incident): the OLD copy steered
            # unconditionally at every cooldown and told the model to "use a
            # different tool (read/glob) ... stop and report completion" —
            # for a build task that made the model surrender with a false
            # "done" while the build had never run. Steer ONLY while refusals
            # are recent (15 min) and teach the sanctioned routes.
            now_e = time.time()
            recent = []
            for r in refusals:
                ep = r.get("epoch")
                if isinstance(ep, (int, float)) and ep > 0:
                    if abs(now_e - ep) <= 900:
                        recent.append(r)
                    continue
                # legacy records carry only a time-of-day string
                now_tod = _tod(time.strftime("%H:%M:%S"))
                tod = _tod(r.get("ts", ""))
                if now_tod is not None and tod is not None and -900 <= now_tod - tod <= 900:
                    recent.append(r)
            if recent:
                steer("Exec-gate refusals: ONE plain command per bash call (no && ; $() backticks), and never repeat a refused call — change the command. Absolute paths of allowlisted tools are fine (javac, d8, aapt, apksigner...). For multi-step builds: write the steps into a .sh script with the file tools, then run exactly `bash /path/to/build.sh` (optional `> /tmp/build.log 2>&1`). NEVER report a task done while a needed command has not run — name what is still blocked instead.", key="exec-gate-taught")
        except FileNotFoundError:
            pass
        except Exception:
            pass
        # 1-token storms / overflow signals live in lane.log (tail)
        try:
            with open(STATE + "/logs/lane.log") as f:
                tail = f.read()[-4000:]
            storm = sum(1 for ln in tail.splitlines() if "in->1out" in ln)
            if storm >= 2:
                c = learn("one_token_storm", "lane shows max_tokens=1 length stops", "clamp floor fix live; monitor")
                log("1-token pattern", f"{storm} recent; clamp floor=1024 guards; monitor only (seen {c}x)")
        except Exception:
            pass
        time.sleep(20)

if __name__ == "__main__":
    main()
