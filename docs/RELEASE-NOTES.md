# CortexAgent — Personal Release Notes

Running log of user-facing changes. Latest first. Companion to the daily
changelog (`docs/superpowers/specs/2026-08-10-daily-changelog.md`), which
tracks the full technical detail.

---

## 2026-08-17 — STT fixed & locked in

**Speech-to-text is now accurate and fast.** The root cause of the garbage
("talk-show" hallucinations, random words, singing) was whisper running on
**CPU** whenever the big model was loaded — CPU whisper hallucinates. It's
now forced onto the **GPU** with a bigger, more accurate model.

- **Model:** faster-whisper `base` on GPU (was `tiny` on CPU) — ~2x more
  accurate, picks up real words instead of making them up.
- **Speed:** no noticeable lag — GPU transcription is instant.
- **VAD sensitivity:** tuned to 0.03 so it catches your voice without
  triggering on background noise.
- **Big model:** retuned to 96k context / ub 2560 — fits alongside STT with
  ~530 MiB free.
- **Backed up:** config snapshot committed to `backup/stt-config-2026-08-17`
  (commit `7986002`) so it can't silently regress.

**Result:** no more hallucinated talk-show prompts, all words picked up,
super fast. ✅
