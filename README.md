# MeetingLens

Local-first meeting intelligence. Ingests meeting audio **and** the screen recording, and produces a typed, source-grounded record of what was decided and promised — then carries those commitments forward into the next meeting with the same people.

Not a transcript summarizer. Action items frequently live on a slide and are never spoken aloud; transcript-only tools lose all of it.

## Why

Every meeting tool summarizes one meeting in prose. Three things are missing:

1. **Slides as input.** "Yeah, so, these" over a list of five deliverables is meaningless as text and obvious with the frame attached.
2. **Typed output.** Decisions, commitments, owners, dates as rows you can query and diff — not paragraphs.
3. **Memory across meetings.** What you promised three weeks ago, still open, surfaced before the call.

## Status

**Phase 1 — in progress.** Ingest, transcription, keyframe extraction, timeline alignment. See `docs/MVP_SPEC.md` §8 for the phase plan.

## Quick start

```bash
make setup      # venv, deps, .env
make up         # postgres + pgvector
make migrate
make demo AUDIO=path/to/audio.wav VIDEO=path/to/screen.mp4
```

Phase 1's only deliverable is that last command printing an interleaved timeline:

```
[00:04:12] SLIDE  "Q3 Roadmap — 1. Migrate warehouse  2. Kill legacy API"
[00:04:15] OTHER  so yeah, these are the priorities
[00:04:22] SELF   who owns the second one?
```

## How it works

```
ingest → asr → keyframes → ocr → caption → align → extract → gaps → ledger → index
```

Each stage is idempotent and resumable, so fixing a prompt never means re-transcribing an hour of audio.

The keyframe stage is where the compression comes from: sample at 1 fps, dHash each frame, commit a keyframe only when the screen has been stable for two seconds. A one-hour presentation goes from roughly 1–2 GB of video to about thirty WebP images and 3 MB — and unlike video, those are indexable.

## Privacy

Everything runs locally by default. Audio, frames and transcripts do not leave the machine unless `LLM_PROVIDER` is explicitly pointed at a cloud provider. No telemetry.

Screen capture sees more than audio ever did — Slack DMs, password managers, other people's data. Capture is scoped to the meeting window and pauses when sharing stops.

Recording participants without disclosure is illegal in two-party-consent states and under GDPR. The consent prompt is part of the capture flow, not an afterthought.

## Deployment — meeting.kargin-utkin.com

The product is local-first, so the domain is **not** where the app runs. Three things live there:

| Path | What | Stack |
|---|---|---|
| `/` | Landing page: the problem, the slide-dedup demo, download links | Next.js static export |
| `/docs` | Install guide, architecture, the decision log | same |
| `/evals` | Public eval table — metrics per model, updated per release | static JSON from `evals/results/` |

Publishing the eval numbers is the point. "Here is commitment recall and fabrication rate across four models on a ten-meeting golden set" is a more convincing artifact than any landing page copy, and almost nobody in this category publishes it.

Deploy as a static build behind Caddy on the existing box. No backend on the public domain — there is nothing to host, and having no server holding meeting data is the product claim.

Optional later: a hosted demo at `/try` that processes a sample recording server-side. Keep it strictly on a fixture, never user uploads.

## Layout

```
api/            FastAPI (local only)
worker/stages/  one module per pipeline stage
core/           config, db, llm providers, media helpers
migrations/     numbered SQL, forward-only
evals/          golden set + metrics
cli/            developer entry point
web/            Next.js — landing, docs, eval table
docs/           MVP_SPEC.md, DECISIONS.md
```

## Working on this with Claude Code

`CLAUDE.md` holds the project rules; `.claude/skills/` holds conventions for recurring work (pipeline stages, migrations, grounded extraction, evals). Read `CLAUDE.md` first — the hard rules there exist because breaking them has a specific cost, not as style preferences.

## License

MIT.
