---
name: pipeline-stage
description: Use when adding, modifying, or debugging any module in worker/stages/. Covers the stage contract, idempotency, the job table, resumability, error handling, and testing. Trigger on any mention of ingest, asr, keyframes, ocr, caption, align, extract, gaps, ledger, or index stages.
---

# Pipeline stage conventions

The pipeline is `ingest → asr → keyframes → ocr → caption → align → extract → gaps → ledger → index`. Each stage is an independent module in `worker/stages/`.

## The contract

Every stage module exports exactly:

```python
STAGE: str                                    # matches the module name

def run(session: Session, meeting_id: int) -> None: ...
```

Rules the contract implies:

- **Pure over DB state.** A stage reads rows written by earlier stages and writes its own. It takes no other input and returns nothing. All communication is through the database.
- **Idempotent.** Running a stage twice on the same meeting produces the same end state. Delete this stage's own rows for the meeting at the top of `run()`, then rewrite them. Never append blindly.
- **Never touch another stage's tables.** `asr` writes `utterance`. `keyframes` writes `keyframe`. `extract` writes `item` and `evidence`. If a stage needs to modify upstream rows, that is a design smell — raise it instead of doing it.
- **No network calls except through `core.llm`** and explicitly declared local subprocesses (ffmpeg, whisper.cpp).

## The job table

The worker loop claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED` and dispatches on `job.stage`. Stages do not manage their own job rows — the loop handles `status`, `attempts`, `started_at`, `finished_at`, and `error`.

A stage signals failure by raising. Two exception types:

- `StageRetryable` — transient (model server down, disk contention). Loop retries with backoff up to 3 attempts.
- `StageFatal` — bad input, unusable media. Loop marks `failed` and does not retry.

Anything else is treated as `StageRetryable`. Be deliberate about which you raise; a fatal error retried three times wastes twenty minutes of GPU time.

## Resumability is the point

The reason for this structure: a one-hour meeting takes real time to transcribe. When `extract` fails because of a prompt bug — and it will, repeatedly — you must be able to fix the prompt and re-run only `extract`. If fixing a prompt forces a re-transcribe, iteration speed dies and so does the project.

Test this explicitly: run the full pipeline, delete the `item` rows, re-run `extract` alone, and assert the result matches.

## Logging

Structured, one line per stage entry and exit, with `meeting_id`, `stage`, duration, and rows written. For stages that call a model, also log model name, token counts, and cost. These numbers go in the eval report and in the writeup.

Never log transcript text or OCR content at INFO. It is meeting content. DEBUG only.

## Long stages

`asr` and `caption` can run for minutes. Write progress into `job` (a `progress` jsonb column is fine) rather than holding state in memory. If the worker is killed mid-stage, the next run starts that stage over — which is acceptable precisely because stages are idempotent.

## Testing a stage

Each stage gets `tests/test_<stage>.py` with:

1. A happy path over a small fixture (a 30-second clip, not a full meeting).
2. An idempotency test: run twice, assert identical rows.
3. An empty-input test: meeting with no video, no audio, or no speech. These happen constantly in real use and are where stages break.

Fixtures live in `tests/fixtures/`. Keep them under 10 MB total. Generate synthetic media with ffmpeg where possible rather than committing real recordings — real meeting audio does not belong in a public repo.

## Adding a new stage

1. Add the module with the contract above.
2. Register it in the stage order list in `worker/run.py`.
3. Add its tables in a migration (see the `db-migration` skill).
4. Add a test.
5. If it changes output quality, add or update a metric (see the `eval-harness` skill).

Do not add a stage that only transforms data already in memory in an adjacent stage. Stage boundaries exist for resumability and cost, not tidiness.
