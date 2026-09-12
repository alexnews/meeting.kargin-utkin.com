# CLAUDE.md

Project instructions for Claude Code. Read this fully before writing code.

## What this is

**MeetingLens** turns a Microsoft Teams meeting recording into one markdown file:
the transcript interleaved with every slide that was on screen, each slide's text
extracted, thumbnails inline, real speaker names.

It is **not** a transcript summarizer, and in v0.1 it is not an AI product at
all. Every output is a mechanical transformation of the input.

Current design: `docs/superpowers/specs/2026-09-11-meetinglens-v0.1-design.md`.
Read it before starting work.

`docs/MVP_SPEC.md` describes a larger, suspended product (typed extraction, gap
detection, a cross-meeting commitment ledger). It is the long-term vision and
**does not describe what is being built.** Do not implement from it.

## Current phase

**v0.1.** Goal: `meetinglens process <mp4> --transcript <vtt>` writes a markdown
file worth reading.

Pipeline: `ingest -> keyframes -> transcript -> ocr -> align -> export`.

**No LLM. No VLM. No embeddings. No web UI. No capture. No Postgres. No Docker.**

If a task seems to need one of those, it belongs to v0.2. Stop and leave a
`TODO(v0.2)` interface rather than starting it.

## Why it is worth building

1. **Slides are first-class input.** Action items often live on a slide and are
   never spoken aloud. Transcript-only tools lose 100% of that.
2. **Teams already gives you speaker-attributed text.** The `.vtt` alongside a
   recording carries real participant names, so v0.1 needs no ASR and no
   diarization on the fast path.
3. **The compression is the headline.** An hour of video becomes about 30 images
   and 3 MB, and unlike video those are searchable.

## Hard rules

1. **No language model anywhere in v0.1.** The tool must be incapable of
   fabricating. If an output cannot be derived mechanically from the input, it
   does not ship in v0.1.
2. **Stages are idempotent and resumable.** Re-running `export` must not
   re-decode the video. State lives in the `job` table.
3. **Decode once, at 1 fps, at the decoder.** `-vf fps=1`. Decoding 30 fps and
   discarding frames is the difference between thirty seconds and twenty minutes.
4. **Local-first.** Nothing leaves the machine. Never add telemetry.
5. **No native platform APIs.** Capture is not in scope. Write the interface and
   `TODO(v0.2)`.
6. **Never record a meeting silently.** Teams announces its own recording, which
   is why it is the supported source. Do not add OBS or any other quiet
   recorder: in a workplace that is a policy and legal risk, not a feature.
7. **Install simplicity outranks architectural preference.** One command, no
   Docker, no brew, no database server. This is why the project uses SQLite
   despite Postgres being the convention everywhere else.

## Known traps

- **Do not decode video at 30 fps and discard frames.** Sample at 1 fps at the
  decoder. See hard rule 3.
- **Animated slide builds** produce near-duplicate frames. Two mechanisms handle
  this: the 2 s stability gate discards mid-build states automatically, and the
  post-OCR superset merge catches builds the presenter talked over. Do not add
  pixel heuristics for it.
- **Gallery view, idle desktop and embedded video playback** are all removed by
  one rule: the post-OCR text density filter. Frames with almost no text are
  worthless for notes and are a privacy problem. Do not write per-case detectors.
- **Teams composites participant thumbnails over shared content**, so OCR picks
  up names and interface noise. Expected. The density filter and superset merge
  absorb most of it.
- **dHash threshold and the stability window are not yet calibrated** against a
  real Teams recording. Both are configurable and both are expected to move.
- **whisper word-level timestamps are unreliable** on the fallback path. Segment
  level is fine for the timeline.

## Stack

Python 3.11+ | SQLite | ffmpeg via `imageio-ffmpeg` (bundled in the wheel) |
RapidOCR on ONNXRuntime | typer | Pillow | numpy | structlog.

Optional extra `[asr]`: faster-whisper, used only when no `.vtt` exists.

Do not introduce new infrastructure without an entry in `docs/DECISIONS.md`.
Adding a dependency needs a reason that survives hard rule 7.

## Layout

```
src/meetinglens/
    cli.py          typer entry point
    config.py       settings
    db.py           sqlite connection + migration runner
    stages/         one module per pipeline stage
    media/          ffmpeg helpers
migrations/         numbered SQL, forward-only
tests/
docs/               MVP_SPEC.md (suspended vision), DECISIONS.md, specs/
```

## Conventions

- Type hints everywhere. `mypy` strict, clean.
- `ruff` for lint and format. Run `make check` before declaring anything done.
- SQL migrations are forward-only and numbered `NNNN_name.sql`. Never edit an
  applied migration.
- Timestamps inside a meeting are **integer milliseconds from meeting start**,
  named `*_ms`. Wall-clock times are ISO 8601 text, named `*_at`. Do not mix.
- Every stage gets a test with a small fixture. **No media files in git, ever** -
  fixtures are generated at test time.
- Commit messages: `stage(keyframes): ...`, `db: ...`, `cli: ...`, `docs: ...`.

## Skills

`.claude/skills/` holds conventions for recurring work.

| Skill | When | Status |
|---|---|---|
| `pipeline-stage` | adding or changing anything in `stages/` | current |
| `db-migration` | any schema change | current, but SQLite now, not Postgres |
| `grounded-extraction` | any LLM call producing structured output | **v0.2, not used** |
| `eval-harness` | metrics and golden fixtures | **v0.2, not used** |

## When you are unsure

Ask before: adding a dependency, changing the schema in a way that drops data,
or starting v0.2 work. Don't ask before: writing tests, refactoring inside a
module, or improving error messages.
