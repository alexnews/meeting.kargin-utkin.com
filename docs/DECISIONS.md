# Decisions

Append-only. One entry per non-obvious choice. Newest last.

Format: context, decision, consequence. Keep each under ten lines.

---

## 0001 — Files in, not live capture, for v0.1

**Context.** Native system-audio capture is platform-specific (ScreenCaptureKit /
Core Audio taps on macOS, WASAPI loopback on Windows, PipeWire on Linux). It is
days of work and unrelated to the part of the product that is actually novel.

**Decision.** v0.1 ingests a recorded audio file and a screen recording. Capture
is Phase 4, and will likely shell out to an existing cross-platform binary
rather than being written from scratch.

**Consequence.** No live coaching in v0.1. The pipeline is batch and resumable,
which is better for iteration anyway.

---

## 0002 — Two-track diarization instead of pyannote

**Context.** Knowing who said what is needed to answer "what did I commit to".
Full diarization is a model, a dependency, and an accuracy problem.

**Decision.** Record mic and system audio as separate tracks. `track='mic'` is
the user; `track='system'` is everyone else. No diarization model in v0.1.

**Consequence.** Individual named speakers among the other participants are not
resolved. For 1:1 calls this is a non-issue; for group calls the extraction
model attributes owners from context and flags low confidence. Splitting the
system track is a Phase 2 refinement.

---

## 0003 — WhisperX rather than whisper.cpp for word timing

**Context.** Whisper was not trained to emit meaningful per-word timestamps.
Precision rounds to roughly one second and can desync badly.

**Decision.** Use WhisperX (forced alignment) where word-level timing matters.
whisper.cpp segment-level output is adequate for the timeline view.

**Consequence.** Heavier Python dependency than a whisper.cpp subprocess. Worth
it: timestamp accuracy is what makes transcript-to-keyframe alignment work, and
alignment is the whole product.

---

## 0004 — Postgres job table, not Celery or Redis

**Context.** The pipeline needs a queue with retries and resumability.

**Decision.** A `job` table claimed with `FOR UPDATE SKIP LOCKED`, polled by a
plain worker loop.

**Consequence.** One fewer service to run for a local-first desktop product.
Throughput is irrelevant here — this processes a handful of meetings a day.
