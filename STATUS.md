# STATUS

Live state. Not a log. Delete lines that stop being true.

**Phase:** v0.1 design rewrite, after a scope pivot on 2026-09-11.

## The pivot

The original five-phase plan in `docs/MVP_SPEC.md` is suspended. The owner needs
a tool usable for real work, installable in one command, and is not willing to
spend months to find out whether local LLM extraction is good enough.

**v0.1 is the deterministic subset only. No LLM anywhere.** Record a Teams
meeting, run one command, get a markdown file: the transcript interleaved with
every slide that was shown, OCR text, thumbnails, real speaker names. Nothing in
it can hallucinate because nothing in it makes a judgement.

Everything else stays designed but unbuilt, reconsidered after the owner has used
v0.1 for a month: LLM extraction, gap detection, the commitment ledger, embeddings
and semantic search, native capture.

## Decided in the pivot, do not relitigate

- **SQLite, not Postgres or pgvector.** One file in `~/.meetinglens/`. No Docker,
  no database server. Vector search at one person's data volume is a numpy dot
  product. This deliberately breaks the owner's cross-project Postgres convention
  because install simplicity is the priority for this project.
- **Microsoft Teams is the recording source.** Teams produces a `.vtt` transcript
  with real participant names alongside the `.mp4`. That removes the ASR step
  entirely on the fast path, removes the model download, gives better speaker
  attribution than the mic/system split, and handles consent because Teams
  notifies all participants that recording started.
- **faster-whisper is a fallback only**, used when no `.vtt` exists. Optional
  install extra, not a base dependency.
- **No OBS.** Recording a work meeting silently is a policy and legal risk that
  Teams-native recording avoids.
- **ffmpeg ships inside the wheel** via `imageio-ffmpeg`. No brew install.
- CI on GitHub-hosted runners while the repository is public. If it ever goes
  private, workflows move to self-hosted in that same commit.

## Where things stand

Repository is public at `git@github.com:alexnews/meeting.kargin-utkin.com.git`,
pushed, on `main`. Two commits. No application code exists yet: the ten stage
stubs in `worker/stages/` all raise `NotImplementedError`, and `core/config.py`,
`core/db.py`, `cli/` entry points and `worker/run.py` do not exist.

`migrations/0001_init.sql` is real but is **now obsolete**: it is Postgres with
pgvector and the schema assumes mic/system tracks. It gets replaced by a SQLite
schema in the rewrite.

## In flight

Rewriting `docs/superpowers/specs/2026-09-11-meetinglens-delivery-design.md`.
Most of it is wrong after the pivot: Postgres, Docker, the five-phase plan, the
mic/system diarization shortcut, and the cassette layer for LLM calls all go.

## Blocked on the owner

- **Does your Teams org produce transcripts?** Open a past recording in OneDrive
  or the Teams chat and check for a transcript tab or `.vtt` download. Yes means
  the fast path; no means the faster-whisper fallback, a 500 MB model download and
  no speaker names. Not blocking: both paths get built.

## Known broken

- Every `make` target fails. The modules they invoke do not exist yet.
- The public README advertises a quick start that does not work, and now also
  describes the wrong architecture. Rewritten as part of v0.1.
- `docs/MVP_SPEC.md` describes the suspended plan. It stays as the long-term
  vision but no longer describes what is being built.
