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

---

## 0005 — SQLite, not Postgres with pgvector

**Context.** v0.1 is a single-user command line tool. Postgres plus pgvector was
the largest install barrier after the models, and v0.1 has no vector search at
all.

**Decision.** One SQLite file at `~/.meetinglens/meetinglens.db`. Supersedes 0004.

**Consequence.** Install is one command with no Docker and no database server.
This deliberately breaks the cross-project Postgres convention, for this project
only, because install simplicity is the stated priority.

---

## 0006 — Teams supplies the transcript, so there is no diarization problem

**Context.** 0002 chose a mic/system two-track split to avoid pyannote. That
required the user to run a separate recorder.

**Decision.** Take the `.vtt` Teams writes alongside its own recording. It
carries real participant names. Supersedes 0002. `faster-whisper` becomes an
optional fallback for meetings with no transcript, superseding 0003.

**Consequence.** No ASR on the fast path, so an hour processes in under a minute
with no model download. Better attribution than mic/system gave. Consent is also
handled, because Teams announces its own recording and a third-party recorder
does not.

---

## 0007 — dHash at 24x24, not the textbook 8x8

**Context.** The 64-bit dHash could not tell slides apart. Measured on rendered
slides: adding a bullet moved 3 bits, while a completely different slide moved
7. No threshold separates a 3 from a 7.

**Decision.** Hash at 24x24, giving 576 bits, with a default threshold of 24.
The same pair measure 12 bits for the build step against 38 for the different
slide, which is a wide, safe window.

**Consequence.** Hashes are 144 hex characters instead of 16, which is
irrelevant at this scale. The measurement is reproduced by the tests in
`tests/test_dhash.py`, so a future change that narrows the window fails CI.

---

## 0008 — A keyframe's image comes from the last frame of its span

**Context.** Slides that build one bullet at a time move the hash very little,
so the whole build stays inside the threshold and forms a single keyframe. Using
the first frame of that span captures the slide with one bullet on it.

**Decision.** `frame_index` is the last sampled frame that matched the keyframe.

**Consequence.** Animated builds resolve to the finished slide with no build
detection, no pixel heuristics and no special case. For a static slide it
changes nothing.

---

## 0009 — The keyframe comparison anchor rolls forward

**Context.** Frames were compared against the hash a keyframe was committed
with. On a three minute fixture with ten topics, two topics vanished: a slide
that builds drifts away from its opening state, and the next slide then looked
similar to that stale opening hash. Two different slides sharing a layout, a
title and two bullet lines, hash close together.

**Decision.** The anchor rolls forward to the most recent matching frame.

**Consequence.** Measured on the fixture: identical frames 0 bits apart, a build
step 6 to 17, a new topic 29 to 44. Frame to frame, a threshold of 24 separates
them with room on both sides. Returning to a slide after a popup is still one
keyframe, because the anchor is only rolled while the screen matches.

---

## 0010 — Threshold 12, and why over-splitting is the safe direction

**Context.** 0007 set the threshold to 24 from two measurements. A wider set,
taken through a real H.264 encode, showed 24 merges slides: two consecutive
slides that share a layout are only 19 bits apart.

    static slide, encoder noise and a moving thumbnail   5 to 7
    build step, one bullet appearing                     5 to 8
    build step, two bullets at once                      17
    slide change, same layout as the one before          19
    slide change, different layout                       29 to 44

**Decision.** Threshold 12, near the low end of the usable 9 to 18 window.

**Consequence.** A build that adds two bullets at once (17) now splits into two
keyframes. That is deliberate and harmless: the post-OCR superset pass collapses
it, because text can distinguish a build from a new slide with certainty where a
perceptual hash cannot. The asymmetry is the whole argument. Splitting too
eagerly is recoverable in the next stage; merging two real slides deletes one
from the output permanently. Bias low.

---

## 0011 — Record audio and screens, never a video

**Context.** The first design ingested a screen recording. A meeting video is
hundreds of megabytes an hour, almost all of it the same slide held still, and
the owner has 16 GB of disk free. It also assumed the meeting platform would
record on request, which many workplaces do not allow.

**Decision.** Capture audio at speech bitrate plus a screenshot only when the
screen changes. No video file is ever written.

**Consequence.** Measured on a real capture: 27 MB an hour for two audio tracks
and about 4 MB for thirty screens, so roughly 31 MB an hour against roughly 800
MB for a screen recording. Two audio devices captured separately also restore
the mic-versus-system speaker split from 0002 without any extra software, since
a meeting application installs its own audio device.

---

## 0012 — Narrow the capture, and never photograph the whole screen silently

**Context.** The first real capture test photographed the entire screen. The
OCR output contained an inbox address, browser tabs and plainly private
material. That is the documented hazard in SECURITY.md, demonstrated in
twenty seconds.

**Decision.** `--app`, `--display` and `--region` narrow what is captured.
Whole-screen capture requires an explicit confirmation, or `--whole-screen` when
not attached to a terminal. A `preview` command takes one screenshot of the
chosen target and opens it, recording nothing.

**Consequence.** The safe thing is the default and the unsafe thing is loud.
`--region` is the strongest option because anything outside the rectangle is
never read at all, and unlike `--app` it needs no Accessibility permission.
