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
pushed, on `main`.

Two calibration findings are already locked in by tests, see DECISIONS 0007 and
0008: the textbook 64-bit dHash cannot tell slides apart (a different slide
moved 7 bits, adding a bullet moved 3), so hashing is 24x24 with a threshold of
24; and a keyframe's image comes from the last frame of its span, which resolves
animated builds to the finished slide with no build detection.

## Built and working

- Package installs: `make setup` then `.venv/bin/meetinglens --help`.
- SQLite schema, forward-only migration runner, idempotent and tested.
- `ingest`: probes the recording, writes the meeting row.
- `keyframes`: decodes once at 1 fps, 24x24 dHash, stability gate, writes WebP.
  Proven end to end against a generated video, not mocks.
- 28 tests, ruff clean, mypy strict clean.

## In flight

Next: `transcript` (Teams .vtt parser, then the faster-whisper fallback), then
`ocr`, then `align` and `export`.

## Blocked on the owner

- **Does your Teams org produce transcripts?** Open a past recording in OneDrive
  or the Teams chat and check for a transcript tab or `.vtt` download. Yes means
  the fast path; no means the faster-whisper fallback, a 500 MB model download and
  no speaker names. Not blocking: both paths get built.

## Known broken

- `meetinglens process` exits 2. It is wired to the database but no stages are
  connected to it yet.
- The public README advertises a quick start that does not work and describes
  the wrong architecture. Rewritten once export lands.
- `docs/MVP_SPEC.md` describes the suspended plan. It stays as the long-term
  vision but no longer describes what is being built.
