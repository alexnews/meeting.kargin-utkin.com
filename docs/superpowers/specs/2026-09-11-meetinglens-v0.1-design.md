# MeetingLens v0.1 design

**Date:** 2026-09-11
**Status:** design, pending implementation plan
**Supersedes:** `2026-09-11-meetinglens-delivery-design.md`

## 1. What this is

A command line tool that turns a Microsoft Teams meeting recording into one
markdown file: the transcript interleaved with every slide that was on screen,
each slide's text extracted, thumbnails inline, real speaker names.

```
meetinglens process ~/Downloads/sync.mp4 --transcript ~/Downloads/sync.vtt
-> ~/Documents/MeetingLens/2026-09-11-sync/2026-09-11-sync.md
```

**Nothing in v0.1 makes a judgement.** There is no language model anywhere in
the pipeline. Every output is a mechanical transformation of the input, so the
tool cannot fabricate, and its failure modes are all visible rather than subtle.

### Out of scope for v0.1

LLM extraction, gap detection, the commitment ledger, embeddings and semantic
search, the pre-meeting brief, native capture, a web UI, Postgres, Docker, and
the public eval table. All of it stays designed in the superseded document and
is reconsidered only after the owner has used v0.1 on real meetings for a month.

### Success criterion

The owner processes their own Teams meetings with it and is still doing so a
month later. Nothing else in this document matters if that does not happen.

## 2. Input

**Primary path: Teams recording plus Teams transcript.** A recorded Teams
meeting produces an `.mp4` in OneDrive and, when transcription is enabled, a
`.vtt` carrying real participant names against every line.

This is materially better than the two-track microphone/system split the old
spec assumed:

- No transcription step, so an hour of meeting processes in under a minute.
- No model download, so `faster-whisper` is an optional extra rather than a
  base dependency.
- Real names rather than `SELF` and `OTHER`, with no diarization model.
- Consent is handled by Teams, which notifies every participant that recording
  started. No third-party recorder runs silently on a work machine.

**Fallback path: no `.vtt`.** Audio is demuxed from the `.mp4` and transcribed
with `faster-whisper`, installed via the `asr` extra. Speaker names are lost and
every utterance is attributed to `Unknown`. Everything else is unchanged.

**Not supported:** OBS or any other silent local recorder. Recording a work
meeting without the platform announcing it is a policy and legal risk that the
Teams-native path avoids for free.

## 3. Pipeline

```
ingest -> keyframes -> transcript -> ocr -> align -> export
```

Each stage is a module under `src/meetinglens/stages/`, is idempotent, records
its state in the `job` table, and can be re-run without re-running its
predecessors. Re-running `export` after editing the template must not re-decode
the video.

### 3.1 ingest

`ffprobe` the container, write the `meeting` row, record duration and title.
Title comes from `--title`, else the filename. Start time comes from
`--started-at`, else the file modification time.

### 3.2 keyframes

The only real algorithm in v0.1.

Decode **once**, at 1 fps, straight to 128x128 grayscale raw frames piped to
stdout:

```
ffmpeg -i in.mp4 -vf "fps=1,scale=128:128:flags=area,format=gray" -f rawvideo -
```

Each frame is 16384 bytes. An hour is about 57 MB streamed, never written to
disk. Decoding at 30 fps and discarding frames is the difference between thirty
seconds and twenty minutes.

Per frame compute a 64-bit dHash, then run this state machine:

```
if committed and hamming(frame, committed) < THRESHOLD:
    committed.end_ms = t              # unchanged, extend the current keyframe
    continue
if candidate is None or hamming(frame, candidate) >= THRESHOLD:
    candidate = new candidate at t     # screen changed, restart the window
else:
    candidate.extend(t)
if candidate.stable_for() >= STABILITY_MS:
    commit(candidate)
```

Committed frames are re-extracted at full resolution by seeking to that single
timestamp and written as WebP q80. Expect roughly 30 frames and 3 MB from an
hour of presentation, against 1 to 2 GB of video.

**Animated builds fall out of the stability gate for free.** While bullets are
appearing, every frame differs from the last, so the candidate window keeps
restarting and nothing commits. The final state is the first one to survive two
seconds, so the committed frame is the complete slide. This is the behaviour the
old spec asked for, achieved by doing nothing extra.

Builds where the presenter talks over each bullet for several seconds do commit
separately. That case is handled after OCR, in §3.6.

### 3.3 transcript

If a `.vtt` is supplied, parse it. Teams writes speakers as a voice span:

```
00:00:03.120 --> 00:00:07.440
<v Alex Kargin>So let us start with the roadmap.</v>
```

Both the `<v Name>` form and the bare `Name:` prefix form are parsed; tenants
differ. Speakers are written to the `speaker` table, deduplicated per meeting.
`is_self` is set by matching against a configured display name.

Otherwise demux audio to 16 kHz mono WAV and run `faster-whisper`, grouping
words into utterances on pauses over 700 ms.

### 3.4 ocr

RapidOCR over every committed keyframe. ONNXRuntime rather than paddlepaddle,
which is a fraction of the install weight and genuinely cross-platform. Reading
order and line breaks are preserved, because slide structure carries meaning.

### 3.5 align

Interval join: each keyframe's `[start_ms, end_ms]` against the utterances
overlapping it. Produces the interleaved timeline that `export` renders.

### 3.6 Two post-OCR passes that replace pixel heuristics

The old spec proposed detecting animated builds, embedded video, gallery view
and idle desktop from pixel statistics. Doing it after OCR is more reliable and
much simpler.

**Superset merge.** If a keyframe's OCR text contains the previous adjacent
keyframe's OCR text as a subset of its lines, the earlier frame is an
intermediate build state. Drop it and extend the later frame backwards. One rule
handles animated builds regardless of how long the presenter talked.

**Text density filter.** Keyframes whose OCR yields fewer than a threshold of
characters are dropped. One deterministic rule removes gallery view, idle
desktop and video playback at once. It is also the privacy control: frames of
people's faces are worthless for notes and are never written to the export.

### 3.7 export

One directory per meeting containing the markdown file and a `keyframes/`
folder, so image links are relative and the export is portable into Obsidian,
Typora, VS Code or a GitHub repository.

```markdown
# Project Sync
2026-09-11 14:00 | 47 min | 23 slides | 412 utterances

## [00:04:12] Slide: Q3 Roadmap

![Q3 Roadmap](keyframes/0007.webp)

> Q3 Roadmap
> 1. Migrate warehouse - AK - Fri
> 2. Kill legacy API
> 3. Pricing model - AK

**[00:04:15] Sarah Chen:** so yeah, these are the priorities
**[00:04:22] Alex Kargin:** who owns the second one?
```

## 4. Storage

**SQLite, one file at `~/.meetinglens/meetinglens.db`.** No Docker, no database
server, no extension to compile.

This deliberately breaks the owner's cross-project Postgres convention. It is
the right call here and only here: this is a single-user desktop tool, and
Postgres plus pgvector is the largest install barrier after the models. Vector
search is not in v0.1 at all, and at one person's data volume it would be a
numpy dot product rather than an index.

Migrations stay forward-only and numbered. `migrations/0001_init.sql` is
replaced rather than amended: it is Postgres with pgvector, it assumes
microphone and system tracks, and it has never been applied to any database, so
the rule against editing an applied migration does not bite.

Timestamps inside a meeting remain integer milliseconds named `*_ms`. Wall clock
times are ISO 8601 text named `*_at`.

```sql
CREATE TABLE meeting (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    transcript_path TEXT,
    started_at      TEXT,
    duration_ms     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE speaker (
    id           INTEGER PRIMARY KEY,
    meeting_id   INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    is_self      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (meeting_id, display_name)
);

CREATE TABLE utterance (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms   INTEGER NOT NULL,
    end_ms     INTEGER NOT NULL,
    speaker_id INTEGER REFERENCES speaker(id),
    text       TEXT NOT NULL,
    source     TEXT NOT NULL          -- vtt | asr
);
CREATE INDEX utterance_meeting_start ON utterance (meeting_id, start_ms);

CREATE TABLE keyframe (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms   INTEGER NOT NULL,
    end_ms     INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    dhash      TEXT NOT NULL,         -- 16 hex characters
    kind       TEXT NOT NULL DEFAULT 'slide',
    ocr_text   TEXT,
    dropped    INTEGER NOT NULL DEFAULT 0,
    drop_reason TEXT                  -- superset | low_text
);
CREATE INDEX keyframe_meeting_start ON keyframe (meeting_id, start_ms);

CREATE TABLE job (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    UNIQUE (meeting_id, stage)
);
```

Dropped keyframes are marked rather than deleted, so a threshold can be retuned
and `export` re-run without re-decoding the video.

## 5. Packaging and install

**The promise: one command, no Docker, no brew.**

```
uv tool install meetinglens
```

| Concern | Choice |
|---|---|
| ffmpeg | `imageio-ffmpeg` ships a binary inside the wheel. No system install |
| OCR | `rapidocr-onnxruntime`, models about 15 MB, fetched on first run |
| Base deps | typer, pillow, numpy, structlog, plus the two above |
| Optional | `meetinglens[asr]` adds faster-whisper, only needed with no `.vtt` |
| Layout | `src/meetinglens/` so the tool is a real distributable package |

The `src/` layout replaces the flat `api/ worker/ core/ cli/` tree in
`CLAUDE.md`, which assumed a deployed application rather than an installable
command. `CLAUDE.md` is updated in the same commit that moves the files.

## 6. Testing and CI

No language model in the pipeline means no cassette layer, no nondeterminism,
and no flaky gate. This is a large simplification over the superseded design.

| Lane | Trigger | Contents |
|---|---|---|
| **fast** | every push | ruff, mypy strict, unit tests. No media, no models |
| **integration** | every push | synthesise a short video with Pillow and ffmpeg at test time, run the whole pipeline, snapshot the markdown output |
| **security** | every push | gitleaks, and a guard blocking any media file or any file over 10 MB |

GitHub-hosted runners while the repository is public: free, and it keeps
strangers' pull requests off the owner's machines. If the repository ever goes
private, the workflows move to self-hosted in that same commit.

**The keyframe state machine is tested with no video at all.** It consumes a
list of hashes, so every case gets a named test from a handwritten sequence: a
static slide, an animated build, a crossfade, a fast-changing video span, and a
gallery span. The integration lane then proves the ffmpeg plumbing feeding it.

**Idempotency is tested, not asserted.** Every stage gets a test that runs it
twice and asserts identical database state.

## 7. Risks

| Risk | Severity | Response |
|---|---|---|
| Owner's Teams tenant has transcription disabled | medium | Fallback path exists. Costs a 500 MB model download and speaker names |
| Teams composites participant thumbnails over shared content, so OCR picks up names and noise | medium | Text density filter and superset merge absorb most of it. Needs a real recording to confirm |
| dHash threshold and stability window are wrong for Teams' encoding | **high** | Both configurable. **Calibrate against one real recording before writing the export stage** |
| Org policy forbids downloading recordings | low | Nothing to do in software. Worth checking before week two |
| Owner stops using it | **high** | The only real risk. Mitigated by v0.1 being one week, not three months |

The threshold calibration risk is why the first real meeting gets processed at
the end of the keyframe stage, not at the end of the project.

## 8. Plan of work

Roughly seven focused days.

| Step | Contents | Done when |
|---|---|---|
| 1 | `src/` restructure, SQLite schema and migration runner, config, CLI skeleton | `meetinglens --help` works after `uv tool install .` |
| 2 | `ingest` | a real Teams mp4 produces a correct meeting row |
| 3 | `keyframes` state machine plus ffmpeg plumbing | **calibrated against one of the owner's real recordings** |
| 4 | `transcript`: VTT parser, then the faster-whisper fallback | speaker names appear from a real Teams vtt |
| 5 | `ocr` and the two post-OCR passes | slide text is clean on the real recording |
| 6 | `align` and `export` | the markdown file is worth reading |
| 7 | CI, packaging, README rewrite | a clean machine installs and runs it |

Step 3 is the checkpoint. If keyframes do not land on the right slides in a real
Teams recording, the project stops there having cost three days.
