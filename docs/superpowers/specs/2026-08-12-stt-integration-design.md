# CortexAgent — Speech-to-Text Integration Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟢 approved (design)

Local-first speech-to-text for the CortexAgent CLI and webui. Replaces the
evaluated Handy app (handy.computer) with a native, shared STT engine.

---

## 1. Goal

Let the user speak to CortexAgent instead of typing, in three places:

1. **CLI** — a global hotkey (hold-to-talk) that records, transcribes, cleans
   up, and types the text at the cursor (works in the terminal and any app).
2. **CLI** — a "speak to capture" mode: always listening, voice-activity
   detection (VAD) starts/stops recording with no button press.
3. **Webui** — a mic button in the composer that records, transcribes, cleans
   up, and fills the textarea for review before sending.

All transcription runs on **CPU** (faster-whisper / CTranslate2). GPU stays
reserved for the big model. Cleanup runs on the always-loaded tiny overseer
(:8082).

## 2. Decisions (user-confirmed 2026-08-12)

| Decision | Choice |
|---|---|
| CLI interaction | Global hotkey → paste at cursor (Handy model) |
| Webui interaction | Mic button → fill textarea → user reviews → send |
| Post-processing | Cleanup via tiny overseer (:8082), fall back to raw |
| Whisper model | faster-whisper `small` (~487MB, CPU) |
| Architecture | Shared engine + two thin transports (Approach A) |
| Capture modes | Hotkey (hold-to-talk) + Speak-to-capture (VAD) |
| Tray | STT settings submenu with checkable toggles |

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    lib/stt.py  (the engine)                 │
│  transcribe(audio) → raw text   (faster-whisper small, CPU) │
│  cleanup(text)     → clean text  (tiny overseer :8082)      │
│  transcribe_and_cleanup(audio) → final text                 │
│  lazy-loaded singleton model · [stt] config section         │
└──────────────┬──────────────────────────────┬──────────────┘
               │                              │
   ┌───────────▼───────────┐      ┌───────────▼──────────────┐
   │  lib/stt_daemon.py     │      │  lib/webui.py + template │
   │  (CLI daemon)          │      │  (webui)                 │
   │  hotkey mode           │      │  🎙️ button in composer   │
   │  speak-to-capture mode │      │  MediaRecorder → blob    │
   │  sounddevice record    │      │  POST /api/stt → text    │
   │  xdotool type @cursor  │      │  fill textarea (review)  │
   └───────────┬────────────┘      └──────────────────────────┘
               │
   ┌───────────▼────────────┐
   │  lib/tray.py           │
   │  STT submenu: toggles  │
   │  speak-to-capture,     │
   │  hotkey, test mic      │
   └────────────────────────┘
```

### Components

| Component | Job | Deps |
|---|---|---|
| `lib/stt.py` | Whisper transcribe + tiny-model cleanup | faster-whisper (installed), sounddevice (to install) |
| `lib/stt_daemon.py` | Hotkey + VAD capture, type at cursor | pynput, sounddevice, xdotool (all present) |
| Webui `/api/stt` | Accept audio blob → engine → return text | stdlib http.server (existing) |
| Tray STT submenu | Toggle modes, test mic, status | pystray (existing) |
| Config `[stt]` | model, hotkey, VAD, cleanup | `lib/config.py` |

## 4. Data Flow

### Hotkey mode (hold-to-talk)
```
press Ctrl+Shift+Space ──► sounddevice records (16kHz mono)
        │  (hold)
release ──► stop recording ──► lib.stt.transcribe() ──► raw text
        │                        │
        │                        ▼
        │              cleanup() → POST :8082 tiny
        │              "Fix punctuation/casing/abbrevs: {text}"
        │                        │
        │                        ▼
        └──► xdotool type --clearmodifiers "<clean text>"
             (typed at cursor — works in terminal, browser, anywhere)
```

### Speak-to-capture mode (VAD)
```
always listening ──► 16kHz ring buffer
        │
VAD detects speech onset (RMS > threshold, debounced ~0.5s)
        │
record until silence ~0.8s
        │
transcribe → cleanup → type at cursor
```

### Webui
```
click 🎙️ ──► MediaRecorder captures (webm/opus) ──► click again to stop
        │
        ▼
POST /api/stt (raw audio body)
        │
        ▼
server: save temp file → lib.stt.transcribe_and_cleanup() → {text}
        │
        ▼
fill #input textarea ──► you review/edit ──► hit Send (existing /api/chat)
```

### Feedback cues
| Event | CLI | Webui |
|---|---|---|
| Recording started | 🔴 tray/terminal cue + beep | 🎙️ button pulses red |
| Recording stopped | beep | button back to normal |
| Transcribing | spinner in status | "transcribing…" in composer |
| Error (no mic, :8082 down) | log + beep + raw fallback | inline error, raw fallback |

**Fallback rule:** if cleanup fails (tiny :8082 down), the raw transcript is
used — STT never blocks on the model.

## 5. Tray Settings

New STT submenu in `lib/tray.py`:

```
CortexAgent
────────────
Reload models · Restart overseer · Reload config
────────────
Launch CLI · Overseer dashboard · Open webui (8090)
────────────
STT
  ☑ Speak to capture      ← checkable toggle → starts/stops VAD mode
  ☐ Hotkey mode           ← checkable toggle → starts/stops hotkey listener
  Model: small            ← read-only status
  Cleanup: tiny           ← read-only status
  Test mic                ← records 2s, transcribes, toasts the result
────────────
Quit
```

Toggles talk to the daemon over a **Unix control socket**
(`~/.cortexagent/state/stt.sock`, same pattern as the overseer control socket)
for start/stop/set-mode commands, plus a state file
(`~/.cortexagent/state/stt_daemon.json`) for status reads (mode, last
transcript, last error). Both modes can be on at once.

## 6. Config

```ini
[stt]
model = small              # faster-whisper: base|small|medium|large
device = cpu               # cpu only (GPU reserved for big model)
hotkey = <ctrl>+<shift>+space
speak_to_capture = true    # VAD always-listening mode
vad_threshold = 0.02       # RMS energy threshold for speech onset
vad_silence_sec = 0.8      # trailing silence to end a clip
cleanup = true             # post-process via tiny overseer
cleanup_target = tiny      # tiny|big|off
```

## 7. Error Handling

| Failure | Behavior |
|---|---|
| No mic / mic busy | Beep + toast "no microphone"; webui shows inline error |
| Whisper model not downloaded | Auto-download on first use (~487MB, one-time) |
| Tiny :8082 down during cleanup | **Fall back to raw transcript** — STT never blocks |
| VAD false trigger | Debounce + threshold config; `Test mic` in tray to calibrate |
| Hotkey conflict (another app) | Log + toast; hotkey remappable in config |
| Webui audio format (webm/opus) | ffmpeg fallback if faster-whisper can't decode |

## 8. Testing

| Test | What it proves |
|---|---|
| `lib/stt.py --test` | Transcribes a bundled sample wav → non-empty text |
| `lib/stt_daemon.py --test` | Records 2s from mic, transcribes, prints (no typing) |
| `cortexagent voice status` | Daemon alive, mode, last transcript, last error |
| Webui `/api/stt` POST sample wav | Returns `{text}` → fills textarea |
| Cleanup fallback | Stop :8082 → raw transcript still pasted |
| Tray toggles | Check/uncheck starts/stops the right mode |

**Smoke gate:** `cortexagent doctor` + `tests/run_smoke.py` extended with the
STT checks.

## 9. Files

| File | Change |
|---|---|
| `lib/stt.py` | NEW — engine (transcribe + cleanup) |
| `lib/stt_daemon.py` | NEW — hotkey + VAD daemon, xdotool typing |
| `lib/config.py` | ADD `[stt]` section + defaults |
| `lib/webui.py` | ADD `/api/stt` endpoint |
| `assets/webui_template.html` | ADD mic button + MediaRecorder JS |
| `lib/tray.py` | ADD STT submenu + toggles |
| `bin/cortexagent` | ADD `voice start|stop|status` subcommand |
| `tests/run_smoke.py` | ADD STT checks |
| `docs/superpowers/specs/2026-08-10-daily-changelog.md` | ADD row |

## 10. Out of Scope (Phase 2)

- Wake-word detection (e.g., "Hey Cortex") — VAD is trigger-free already
- Speaker diarization / multi-voice separation
- On-device phone STT (S24 FE) — separate future phase
- Emotion detection (explicitly not wanted)
- Streaming (partial) transcription — clip-based only for v1
