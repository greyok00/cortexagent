# SUPERVISOR STATUS (updated by heal.py every 20s; watch.py incidents below)

## Machine plane: LIVE ✅
- model :7090 13107ctx/15364MiB all-VRAM (systemd cortexagent-model)
- lane :7091 lossless (systemd cortexagent-lane)
- heal.py: machine healer + lessons (lessons.jsonl)
- watch.py: session incident detector (incidents.jsonl)

## Pending for next TUI restart (not loaded in the CURRENT session):
- loop guards (streak killer), teachable refusals, visual-chat ext,
  supervised-steer channel, monochrome-16 theme default, 50ms render.

## Known-active incidents in the current session:
- see incidents.jsonl (watcher streams it)
