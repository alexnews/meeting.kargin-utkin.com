# MeetingLens — MVP Specification

**Author:** Alex Kargin
**Purpose:** Hand this file to Claude Code as the project brief.
**Thesis:** Meeting notes tools summarize transcripts. This one builds a *typed, source-grounded case file* from audio **and** slides, detects what is missing, and carries commitments across meetings.

This is the same engine as ClaimLens / BookkeeperLens / FranchiseLens, pointed at a new input type:

> ingest messy multimodal input → extract into a typed schema → ground every field to its exact source → run a gap-detection pass → export something auditable

---

## 1. Why this is not another notetaker

The market is crowded (Meetily ~30k stars, Anarlog, Granola, Otter, Fireflies). Do not compete on "AI summary of my call." Compete on three things nobody does well:

1. **Slides are first-class input.** Action items very often live on a slide and are *never spoken aloud*. Someone shares a list of five deliverables and says "yeah, so, these." Transcript-only tools lose 100% of that content. This is the single strongest differentiator.
2. **Typed extraction, not prose.** Output is a schema (decisions, commitments, owners, dates, risks), not a paragraph. Schemas can be queried, diffed, and validated. Prose cannot.
3. **Cross-meeting commitment ledger.** Every tool summarizes one meeting. Almost none tell you: *three weeks ago you promised Sarah a pricing model, it is still open, and she is on this call in ten minutes.*

If you build 1 and 3 and skip everything else, you still have a better product than most of the field.

---

## 2. MVP scope

### In scope (v0.1)

- Ingest a **recorded** meeting: one audio file + one screen-recording video file
- Transcription with speaker attribution (via dual-track trick, see §5.2)
- Keyframe extraction with deduplication
- OCR + vision captioning on keyframes only
- Timeline alignment of transcript ↔ keyframes
- Typed extraction with per-field grounding
- Gap detection pass
- Cross-meeting commitment ledger
- Pre-meeting brief generation
- Eval harness with a golden set

### Explicitly OUT of scope for v0.1

- **Live capture.** This is the single biggest scope trap. System-audio capture is platform-specific native code (ScreenCaptureKit / Core Audio taps on macOS, WASAPI loopback on Windows, PipeWire on Linux) and it is *not* something to get working overnight. v0.1 ingests files. Capture is Phase 3.
- Real-time transcription / live coaching overlay
- Meeting bots that join Zoom/Meet/Teams
- Calendar integration (stub the interface, hardcode participants)
- Multi-user, auth, teams, sharing
- Mobile

**Rule for the agent:** if a task requires native platform APIs, stop and leave a `TODO(phase3)` interface instead. Do not attempt it.

---

## 3. Stack

Chosen to match existing infrastructure — no new operational surface.

| Layer | Choice | Note |
|---|---|---|
| API | FastAPI (Python 3.11+) | |
| DB | PostgreSQL 16 + `pgvector` | canonical store |
| Queue | Postgres-backed job table + a worker loop | do not add Celery/Redis for v0.1 |
| Orchestration | plain Python worker; Airflow only if it already exists | |
| ASR | `whisper.cpp` large-v3-turbo (Metal/CUDA) | subprocess call, not the Python package |
| OCR | PaddleOCR (cross-platform) | Tesseract fails on dark themes and mixed fonts |
| Vision | local VLM via Ollama (`qwen2.5-vl` or similar) | NVIDIA NIM free tier as fallback |
| LLM | Ollama local; provider abstraction with failover | same pattern as Boss.cc |
| Embeddings | local model via Ollama → `pgvector` | |
| Frontend | Next.js + TypeScript | |
| Video/audio | `ffmpeg` subprocess | |

**Provider abstraction is mandatory.** One `LLMProvider` interface, implementations for Ollama / NIM / Anthropic / OpenAI, config-selected, with failover. Never call a provider SDK directly from pipeline code.

---

## 4. Data model

Write this as migrations. It is the spine of the project — get it right before any pipeline code.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- ============ core ============

CREATE TABLE meeting (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    duration_s      INTEGER,
    source          TEXT NOT NULL DEFAULT 'upload',   -- upload | capture
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|done|failed
    audio_path      TEXT,
    video_path      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE person (
    id              BIGSERIAL PRIMARY KEY,
    display_name    TEXT NOT NULL,
    email           TEXT UNIQUE,
    org             TEXT,
    is_self         BOOLEAN NOT NULL DEFAULT false,
    aliases         TEXT[] DEFAULT '{}',              -- name variants heard in transcripts
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meeting_participant (
    meeting_id      BIGINT REFERENCES meeting(id) ON DELETE CASCADE,
    person_id       BIGINT REFERENCES person(id),
    PRIMARY KEY (meeting_id, person_id)
);

-- ============ transcript ============

CREATE TABLE utterance (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    track           TEXT NOT NULL,        -- 'mic' | 'system'
    speaker_id      BIGINT REFERENCES person(id),
    speaker_label   TEXT,                 -- raw label before resolution
    text            TEXT NOT NULL,
    confidence      REAL,
    embedding       vector(768)
);
CREATE INDEX ON utterance (meeting_id, start_ms);
CREATE INDEX ON utterance USING hnsw (embedding vector_cosine_ops);

-- ============ visual ============

CREATE TABLE keyframe (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,     -- when this visual state appeared
    end_ms          INTEGER NOT NULL,     -- when it was replaced
    image_path      TEXT NOT NULL,        -- WebP q80
    dhash           BIT(64) NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'slide',  -- slide|document|code|video_segment|manual
    is_manual       BOOLEAN NOT NULL DEFAULT false, -- user pressed the hotkey
    ocr_text        TEXT,
    caption         TEXT,                 -- VLM description
    embedding       vector(768)           -- over ocr_text || caption
);
CREATE INDEX ON keyframe (meeting_id, start_ms);
CREATE INDEX ON keyframe USING hnsw (embedding vector_cosine_ops);

-- ============ typed extraction ============

CREATE TABLE item (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,        -- decision|commitment|open_question|risk|topic
    title           TEXT NOT NULL,
    detail          TEXT,
    owner_id        BIGINT REFERENCES person(id),
    due_date        DATE,
    confidence      REAL NOT NULL,
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    review_reason   TEXT,                 -- why gap detection flagged it
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON item (meeting_id, kind);
CREATE INDEX ON item USING hnsw (embedding vector_cosine_ops);

-- every extracted field must point back at its source
CREATE TABLE evidence (
    id              BIGSERIAL PRIMARY KEY,
    item_id         BIGINT NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,        -- 'utterance' | 'keyframe'
    utterance_id    BIGINT REFERENCES utterance(id),
    keyframe_id     BIGINT REFERENCES keyframe(id),
    quote           TEXT,                 -- short supporting span
    CHECK (
        (source_type = 'utterance' AND utterance_id IS NOT NULL) OR
        (source_type = 'keyframe'  AND keyframe_id  IS NOT NULL)
    )
);

-- ============ cross-meeting ledger ============

CREATE TABLE commitment (
    id              BIGSERIAL PRIMARY KEY,
    item_id         BIGINT NOT NULL REFERENCES item(id),
    owner_id        BIGINT REFERENCES person(id),
    counterparty_id BIGINT REFERENCES person(id),
    status          TEXT NOT NULL DEFAULT 'open',  -- open|done|dropped|superseded
    due_date        DATE,
    opened_meeting  BIGINT REFERENCES meeting(id),
    closed_meeting  BIGINT REFERENCES meeting(id),
    closed_reason   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON commitment (owner_id, status);
CREATE INDEX ON commitment (counterparty_id, status);

-- ============ jobs ============

CREATE TABLE job (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT REFERENCES meeting(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);
```

---

## 5. Pipeline

Each stage is a separate, idempotent, resumable worker keyed on `job.stage`. A failure in stage 4 must not force re-running stage 1.

```
ingest → asr → keyframes → ocr → caption → align → extract → gaps → ledger → index
```

### 5.1 `ingest`
- Probe with `ffprobe`, write `meeting` row, normalize audio to 16 kHz mono WAV per track.
- If the upload is a single video file, demux audio from it.

### 5.2 `asr` — the diarization shortcut

**Do not use pyannote for v0.1.** If mic and system audio are recorded as two separate tracks, speaker separation is nearly free:

- `track = 'mic'` → **you** (`person.is_self = true`)
- `track = 'system'` → **everyone else**

That single distinction covers the majority of the product value ("what did *I* commit to"). Splitting the system track into individual named speakers is a Phase 2 refinement, and for 1:1 calls it is not needed at all.

If only a single mixed track exists, fall back to labeling everything `unknown` and let the extraction model attribute owners from context ("Sarah, can you take that?").

Run `whisper.cpp` per track, emit word-level timestamps, group into utterances on pauses > 700 ms.

### 5.3 `keyframes` — change detection

The core algorithm. **Do not decode 30 fps and throw frames away.**

```
sample video at 1 fps
for each frame:
    downscale to 128x128 grayscale
    compute 64-bit dHash
    hamming = distance(dhash, last_committed_dhash)
    if hamming < 8:            # unchanged
        extend candidate.end_ms
        continue
    # screen changed — start a stability window
    if the new state persists unchanged for >= 2.0s:
        commit candidate keyframe, start new candidate
    else:
        discard (mid-transition / crossfade)
```

Edge cases that must be handled — these are what make it good rather than naive:

| Case | Behaviour |
|---|---|
| **Animated builds** (bullets appearing one by one) | Keep the **last** stable frame of the build sequence, not the first. The final state contains all the content. Detect by: successive frames where change is strictly additive in the lower region. |
| **Mid-transition frames** | The 2 s stability gate discards them. |
| **Embedded video playback** | Sustained high change-rate → rate-limit that span to 1 frame per 30 s, set `kind='video_segment'`. |
| **Gallery view / no screen share** | Faces are worthless to store and a privacy problem. Skip spans where no share is active. Heuristic for uploads: high inter-frame change with low text density from a quick OCR probe. |
| **Screen idle / desktop visible** | Skip. Low text density + no change. |

Write committed frames as WebP q80. Expected result: **~30 frames and ~3 MB for a one-hour presentation**, versus 1–2 GB for the raw video. This ratio is the headline of the write-up.

### 5.4 `ocr`
PaddleOCR on each committed keyframe → `keyframe.ocr_text`. Preserve reading order and line breaks; slide structure carries meaning.

### 5.5 `caption`
VLM over committed keyframes **only**, batched, after the meeting. ~30 frames is cents.

OCR gives you axis labels. The VLM gives you *"revenue declined in Q3 and the deck attributes it to churn."* Both are needed. Prompt it for: what kind of artifact this is, what it claims, and any list of tasks/owners/dates visible.

### 5.6 `align`
Join each keyframe's `[start_ms, end_ms]` to the utterances overlapping it. Produces the interleaved timeline that everything downstream consumes:

```
[00:04:12] SLIDE: "Q3 Roadmap — 1. Migrate warehouse 2. Kill legacy API ..."
[00:04:15] OTHER: "so yeah, these are the priorities"
[00:04:22] SELF:  "who owns the second one?"
```

Feed **this**, not a bare transcript, to the extraction model. This is the whole point.

### 5.7 `extract` — typed schema

Structured output, one call per timeline chunk (~15 min windows with 2 min overlap), then a merge pass.

```json
{
  "items": [{
    "kind": "commitment",
    "title": "Send pricing model to Sarah",
    "detail": "Three-tier model with usage-based overage",
    "owner": "self",
    "due_date": "2026-09-19",
    "confidence": 0.86,
    "evidence": [
      {"source_type": "utterance", "ref": 4412, "quote": "I'll get you the pricing"},
      {"source_type": "keyframe",  "ref": 87,   "quote": "Pricing model — AK — Fri"}
    ]
  }]
}
```

Hard rules in the system prompt:
- Every item MUST have at least one evidence reference. No evidence → drop the item.
- Never infer a `due_date` that was not stated or shown. Null is correct.
- `owner` must be `self`, a named participant, or null. Never guess.
- Prefer under-extraction. A missed item is recoverable; a fabricated commitment destroys trust in the whole product.

Resolve `ref` IDs against the DB after parsing and **reject any item whose refs do not exist** — this is your hallucination guard, same as the PodTalk fact-check pass.

### 5.8 `gaps` — the differentiator

A separate pass over extracted items. Sets `needs_review` + `review_reason`:

- Commitment with **no owner**
- Commitment with **no due date**
- Decision with **no stated rationale**
- **Slide bullet that was never spoken about.** ← the flagship check. Diff `keyframe.ocr_text` bullet lines against the aligned transcript span. A deliverable listed on a slide with zero verbal discussion is exactly what every other tool loses.
- Open question raised and never returned to (no later utterance semantically similar)
- Commitment attributed to someone not in the participant list

### 5.9 `ledger`
- New commitments → `commitment` rows, `status='open'`.
- Match against existing open commitments by embedding similarity + owner + counterparty (threshold ~0.85). On match, decide `done` / `superseded` / still `open` from the current meeting's evidence.
- Never auto-close on weak evidence. Leave open and flag.

---

## 6. Pre-meeting brief

The feature that closes the loop. Input: participant list (+ optional title/agenda).

```
1. Fetch open commitments where owner=self AND counterparty IN participants
2. Fetch open commitments where owner IN participants AND counterparty=self
3. Fetch unresolved open_questions from the last N meetings with these people
4. Vector search past items by agenda text, scoped to these participants
5. Generate: "what you owe / what they owe / still unresolved / suggested talking points"
```

Every line cites the meeting and timestamp it came from. Render the keyframe thumbnail inline when the source is a slide — showing the actual pricing slide beats paraphrasing it.

---

## 7. Eval harness

Build this in Phase 1, not at the end. It is also the most credible thing in the write-up and the thing an interviewer will ask about.

**Golden set:** 10 recorded meetings, hand-labelled with the true set of decisions and commitments. Include at least two with slide-only action items and one with a heavy accent or cross-talk.

**Metrics:**

| Metric | Target |
|---|---|
| Commitment recall | > 0.85 |
| Commitment precision | > 0.90 |
| **Fabrication rate** (item with no valid supporting evidence) | **0.00** |
| Grounding accuracy (evidence ref actually supports the claim, sampled) | > 0.95 |
| Slide-only item recall (items present on a slide, never spoken) | > 0.70 |
| Keyframe compression ratio | report it |
| Cost + wall-clock per meeting-hour | report it |

`make eval` prints a table. Regressions block merges. Track results per model so the local-vs-cloud comparison is empirical, not vibes.

---

## 8. Build order

**Phase 1 — one night, the spine.**
Migrations. `ingest` + `asr` + `keyframes` + `align`. A CLI that takes two files and prints the interleaved timeline. No LLM yet, no UI, no OCR. If the timeline looks right, everything else follows. If it does not, nothing else matters.

**Phase 2 — the value.**
`ocr` + `caption` + `extract` + `gaps`. Eval harness with 3 golden meetings. Minimal Next.js page: timeline, keyframes, typed items with evidence links.

**Phase 3 — memory.**
`ledger`, pre-meeting brief, cross-meeting search. This is the part nobody else has. Expand golden set to 10.

**Phase 4 — capture.**
Native audio + screen capture per platform. Global hotkey for manual frame grab (grabs current frame + surrounding ±30 s of transcript, `is_manual=true`, weighted higher in extraction and retrieval — an explicit human signal is the strongest relevance feature available).

**Phase 5 — release.** Package, document, publish.

---

## 9. Non-negotiables

- **Local-first by default.** No audio, frames, or transcripts leave the machine unless explicitly configured. This is the existing editorial position and it is also the honest reason to build it.
- **Consent.** Recording participants without disclosure is illegal in two-party-consent states and under GDPR. Build the disclosure prompt into the capture flow from day one, not as a later patch.
- **Screen capture sees everything.** Slack DMs, password managers, other clients' data. Capture the meeting window only, pause on focus loss or share stop, and offer a redaction pass. Audio never had this exposure; screen capture does.
- **Fabrication is the only unrecoverable failure.** Every quality tradeoff resolves toward "say less."

---

## 10. Notes for the coding agent

- Read this whole file before writing code.
- Start with migrations and the `align` output format. Get the timeline right first.
- Each pipeline stage: separate module, pure function over DB state, idempotent, own test.
- Never call an LLM SDK directly from pipeline code — go through `LLMProvider`.
- If a task needs native platform APIs, write the interface and `TODO(phase3)`. Do not attempt it.
- Ship Phase 1 complete rather than all five phases half-built.
