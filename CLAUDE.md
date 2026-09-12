# CLAUDE.md

Project instructions for Claude Code. Read this fully before writing code.

## What this is

**MeetingLens** — a local-first meeting intelligence tool. It ingests meeting audio **and** the screen recording, and produces a typed, source-grounded record of what was decided and promised, then carries those commitments across meetings.

It is **not** a transcript summarizer. That market is saturated. The thesis:

> ingest messy multimodal input → extract into a **typed schema** → ground every field to its exact source → run a **gap-detection** pass → export something auditable

Full spec: `docs/MVP_SPEC.md`. Read it before starting a new stage.

## Three things that make this different

1. **Slides are first-class input.** Action items often live on a slide and are never spoken aloud. Transcript-only tools lose 100% of that. This is the flagship capability.
2. **Typed extraction, not prose.** Output is queryable rows, not paragraphs.
3. **Cross-meeting commitment ledger.** "You promised Sarah a pricing model three weeks ago, it's still open, she's on this call."

If a proposed feature doesn't serve one of these, it is out of scope.

## Current phase

**PHASE 1.** Goal: migrations + `ingest` + `asr` + `keyframes` + `align`, and a CLI that takes an audio file and a screen recording and prints the interleaved timeline.

No LLM calls. No OCR. No web UI. No capture.

Phase 1 is done when `make demo FILE=...` prints something like:

```
[00:04:12] SLIDE  "Q3 Roadmap — 1. Migrate warehouse  2. Kill legacy API"
[00:04:15] OTHER  so yeah, these are the priorities
[00:04:22] SELF   who owns the second one?
```

Do not start Phase 2 work. If a Phase 1 task seems to need a Phase 2 component, stub the interface and leave `TODO(phase2)`.

Phases 2–5 are in `docs/MVP_SPEC.md` §8.

## Hard rules

1. **Never call an LLM SDK directly from pipeline code.** Everything goes through `core.llm.base.LLMProvider`. Config selects the implementation. This makes the local-vs-cloud comparison empirical.
2. **Fabrication is the only unrecoverable failure.** Every extracted item must carry at least one evidence reference that resolves to a real row. Items with unresolvable refs are dropped, not repaired. Prefer under-extraction.
3. **Never infer a date, owner, or figure that was not stated or shown.** `NULL` is a correct answer.
4. **Stages are idempotent and resumable.** Re-running `extract` must not require re-running `asr`. State lives in the `job` table.
5. **No native platform APIs before Phase 4.** If a task needs ScreenCaptureKit, WASAPI, or PipeWire, write the interface and `TODO(phase4)`. Do not attempt it.
6. **Local-first.** No audio, frames, or transcripts leave the machine unless `LLM_PROVIDER` is explicitly set to a cloud provider. Never add telemetry.
7. **Ship one phase complete** rather than five phases half-built.

## Known traps

- **whisper.cpp word-level timestamps are unreliable.** Whisper was not trained to emit meaningful per-word timing; precision rounds to ~1s and can desync. Use **WhisperX** (forced alignment) when word-level timing matters. Segment-level from whisper.cpp is fine for the timeline.
- **Do not decode video at 30 fps and discard frames.** Sample at 1 fps at the decoder (`-vf fps=1`). Decoding everything is the difference between 30 seconds and 20 minutes.
- **Diarization: use the two-track shortcut.** `track='mic'` is the user, `track='system'` is everyone else. Do not add pyannote in Phase 1. This single distinction covers "what did *I* commit to," which is most of the value.
- **Animated slide builds** produce near-duplicate frames. Keep the **last** stable frame of a build, not the first.
- **ScreenCaptureKit audio is not isolated** — notifications and music get mixed in. Relevant in Phase 4.

## Stack

Python 3.11+ · FastAPI · PostgreSQL 16 + pgvector · plain Postgres-backed job queue (no Celery, no Redis) · whisper.cpp / WhisperX · PaddleOCR · Ollama for LLM and VLM · Next.js + TypeScript · ffmpeg via subprocess.

Do not introduce new infrastructure without an entry in `docs/DECISIONS.md`.

## Layout

```
api/            FastAPI app
worker/stages/  one module per pipeline stage — the heart of the project
core/           config, db, models, llm providers, media helpers
migrations/     numbered SQL, forward-only
evals/          golden set + metrics; build this early, not last
cli/            developer entry point
web/            Next.js frontend (Phase 2+)
docs/           MVP_SPEC.md, DECISIONS.md
storage/        gitignored media
```

## Conventions

- Type hints everywhere. `mypy` clean.
- `ruff` for lint and format. Run `make check` before declaring anything done.
- SQL migrations are forward-only and numbered `NNNN_name.sql`. Never edit an applied migration.
- Timestamps inside a meeting are **integer milliseconds from meeting start**, named `*_ms`. Wall-clock times are `TIMESTAMPTZ`, named `*_at`. Do not mix them.
- Every stage gets a test with a small fixture. No fixture over 10 MB in git.
- Commit messages: `stage(asr): ...`, `db: ...`, `eval: ...`.

## Skills

`.claude/skills/` contains conventions for recurring work. Read the relevant one before starting:

| Skill | When |
|---|---|
| `pipeline-stage` | adding or changing anything in `worker/stages/` |
| `db-migration` | any schema change |
| `grounded-extraction` | any LLM call that produces structured output |
| `eval-harness` | adding metrics or golden fixtures |

## When you are unsure

Ask before: adding a dependency, changing the schema in a way that drops data, or starting a phase that isn't the current one. Don't ask before: writing tests, refactoring inside a module, or improving error messages.
