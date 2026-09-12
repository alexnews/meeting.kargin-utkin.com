# STATUS

Live state. Not a log. Delete lines that stop being true.

**Phase:** 0 (delivery machinery). See `docs/superpowers/specs/2026-09-11-meetinglens-delivery-design.md`.

## Where things stand

Git repository initialised on `main` and pushed to
`git@github.com:alexnews/meeting.kargin-utkin.com.git`. The repository is
public. The scaffold is unpacked and committed.

There is no application code yet: all ten stage modules in `worker/stages/` are
seven-line stubs that raise `NotImplementedError`, `core/llm/base.py` defines the
Protocol but `get_provider()` raises, and `core/config.py`, `core/db.py`,
`core/models.py`, `cli/migrate.py`, `cli/meetinglens.py`, `worker/run.py` and
`api/main.py` do not exist. The Makefile targets point at those missing modules,
so every target except `help` currently fails. `migrations/0001_init.sql` is real
and complete.

## Blocked on the owner

- **Design spec review.** The delivery design has not been explicitly approved.
  It is pushed but no code depends on it yet, so changing it is still cheap.

## Not started

Phase 0 remaining: CI workflows (lanes A, B, S), gitleaks and the large-file
guard, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
`CHANGELOG.md`, `deploy.sh`, the static site skeleton, and the two new
`DECISIONS.md` entries (hosted-runner exception, ASR and OCR stack swaps).

Phase 0 is done when a deliberately broken pull request goes red, a fixed one
goes green, and both gitleaks and the large-file guard provably block a test
commit.

## Known broken

- `make setup`, `make migrate`, `make demo` and every other target fail. Expected
  at Phase 0; the modules they invoke are written in Phase 1.
- **The public README promises commands that do not work.** Its quick start shows
  `make setup` through `make demo`. On a public repository that reads as a
  broken project to anyone who tries it. Phase 0 fixes this by marking the quick
  start as not yet available and saying plainly what does work today.

## Decided, do not relitigate

- CI runs on GitHub-hosted runners while this repository is public. Free, and it
  keeps strangers' pull requests off the production box. If the repository ever
  goes private, the workflows move to self-hosted in that same commit.
- Deploy stays a manual `./deploy.sh`. No timer, no polling, no push-to-deploy.
- Real-model evals run manually on the owner's Mac, not in CI. A laptop is the
  deployment target, so laptop numbers are the honest ones.
- ASR default is faster-whisper; OCR is RapidOCR. whisper.cpp and WhisperX stay
  as opt-in backends and all three get benchmarked on the golden set.
