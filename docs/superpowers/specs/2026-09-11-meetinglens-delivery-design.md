# MeetingLens delivery design

**Date:** 2026-09-11
**Status:** approved design, pending implementation plan
**Scope:** how MeetingLens gets built, tested, secured and published across Phases 0-5.

This document does not restate the product. `docs/MVP_SPEC.md` is the product
spec and remains authoritative for what the pipeline does. This document covers
everything around it: repository, CI, determinism, fixtures, evals, security,
install, and the phase gates. Where it contradicts `MVP_SPEC.md`, §11 lists the
amendments and this document wins.

---

## 1. Goals

The project has three success criteria, in the owner's words. They are design
constraints, not aspirations.

1. **Daily personal use.** The owner keeps meeting notes with it. Implication:
   the tool must be usable on real meetings from Phase 2, long before native
   capture exists, and must export into the notes the owner already reads.
2. **Public credibility.** The repository is public and is meant to earn trust.
   Implication: a stranger must get from landing page to a working demo in about
   sixty seconds, with Docker as the only prerequisite.
3. **Hiring signal.** The repository is read by engineers evaluating the owner.
   Implication: install experience, test quality, security posture and the
   decision log are judged artifacts, equal in weight to the feature list.

A non-goal: growth. No telemetry, no analytics, no signup. The repository and
the published eval numbers are the entire distribution strategy.

## 2. Success measures

| Goal | Measure |
|---|---|
| Daily use | Owner processes their own meetings from Phase 2 onward |
| Credibility | `docker compose up && make demo` works on a clean machine with no model downloads |
| Hiring signal | Public eval table with commitment recall, precision and fabrication rate per model |

---

## 3. Repository and delivery machinery

### 3.1 Layout

The git repository root is the project root. Phase 0 unpacks
`meetinglens-scaffold.tar.gz` into it. Every root-level file currently present
(`README.md`, `CLAUDE.md`, `0001_init.sql`, `MEETINGLENS_MVP.md`) is byte
identical to its copy inside the tarball, so the unpack is a clean replace: the
loose duplicates and the tarball itself are deleted in the same commit.

Layout is as `MVP_SPEC.md` specifies, plus:

```
.github/workflows/     ci.yml, security.yml
docs/superpowers/      specs and implementation plans
evals/fixtures/        synthetic meeting generator + YAML scripts
evals/results/         one committed JSON per eval run
evals/baselines/       current.json, what lane C regresses against
tests/cassettes/       recorded responses for every nondeterministic boundary
deploy.sh              manual deploy of the static site
STATUS.md              live state, per the owner's global convention
```

### 3.2 Community and security files

Present from Phase 0: `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `CHANGELOG.md`.

`SECURITY.md` covers two distinct things and must not conflate them:

- How to report a vulnerability in the software.
- **The product's own threat model.** Screen capture sees password managers,
  Slack DMs and other people's confidential material. Audio never had this
  exposure. The document states what is captured, what is stored, what leaves
  the machine and under exactly which configuration. This is a trust signal
  that costs nothing and that competitors do not offer.

### 3.3 Deployment

`meeting.kargin-utkin.com` serves a static Next.js export behind Caddy:
landing page, docs, and the public eval table. There is no backend on the
public domain, and that absence is itself a product claim.

Deploy is manual, per the owner's standing rule: `cd <path> && ./deploy.sh`.
One invocation pulls, installs, builds the static export, reloads Caddy, curls
the three pages as a smoke test, and prints the deployed commit. No timer, no
polling job, no push-triggered deploy.

---

## 4. CI architecture

### 4.1 Runner decision

**GitHub-hosted runners, for as long as this repository is public.**

This is a deliberate, scoped exception to the owner's global rule against
hosted runners. The rule exists because hosted minutes are billed on private
repositories and have cost real money. On a public repository Actions minutes
are free and unlimited, so the rule's stated reason does not apply.

Separately, the alternative is now actively unsafe. A self-hosted runner on a
public repository lets any stranger execute code on the host by opening a pull
request, and the default runner is not ephemeral, so a job can persist state
into later runs. The production box serves the domain. GitHub's own guidance
recommends against this configuration.

**Condition:** if this repository is ever made private, the workflows move to a
self-hosted runner in the same commit that flips the visibility. This condition
is recorded in `docs/DECISIONS.md` so a future session finds it.

### 4.2 Lanes

| Lane | Runner | Trigger | Budget | Contents |
|---|---|---|---|---|
| **A fast** | hosted | every push, every PR | ~2 min | ruff check, ruff format --check, mypy strict, unit tests, migrations applied forward against an ephemeral Postgres service, schema drift check |
| **B integration** | hosted | every push, every PR | ~10 min | Postgres with pgvector as a service container, real ffmpeg, fixtures generated from YAML at runtime, full pipeline from ingest to ledger with cassettes, golden-file snapshot of the timeline, idempotency and resume tests |
| **C eval** | owner's Mac | `make eval`, manual | minutes | real faster-whisper, real Ollama LLM and VLM. Writes `evals/results/*.json`, diffs against `evals/baselines/current.json`, prints the table |
| **S security** | hosted | every push | ~1 min | gitleaks, pip-audit, the large-file and media guard |

Lane C is deliberately not automated. Real-model numbers belong on a laptop
because a laptop is the deployment target: nobody runs MeetingLens on a server.
Results are committed as JSON by the person who ran them, with the host and
model recorded in the file.

### 4.3 Two QA mechanisms that carry disproportionate weight

**Idempotency is tested, not asserted.** Hard rule 4 says stages are idempotent
and resumable. Every stage gets two tests: run twice, assert identical database
state; and interrupt mid-stage, resume, assert the same final state as an
uninterrupted run. Untested idempotency claims are usually false.

**Schema drift check.** Generate DDL from the SQLAlchemy models, diff against
the state produced by applying migrations in order, fail on divergence. Catches
the common failure where a model and its migration quietly disagree.

---

## 5. Determinism: the cassette layer

Per-push testing is worthless if it flakes, and every interesting part of this
pipeline calls a nondeterministic external system. The mechanism is record and
replay at each of those boundaries.

`core/testing/cassettes.py` wraps a call, hashes the request, and reads or
writes `tests/cassettes/<boundary>/<hash>.json`.

Modes, via `CASSETTE_MODE`:

- `replay` - serve from disk; a miss calls the real thing and records it.
  Local development convenience only
- `record` - call the real thing, write the response
- `strict` - replay, and a miss fails the test rather than falling through to a
  live call. This is the CI setting.

**Four boundaries use the same mechanism:** LLM, VLM, ASR, OCR. This is what
lets a hosted runner with no model files execute the entire pipeline.

Rejected alternatives:

- **Handwritten fake provider only.** Never sees real model output, so the
  parser breaks on first contact with reality. Retained for edge cases, not as
  the primary mechanism.
- **A small real model in CI.** Nondeterministic, slow, and a 1.5b model's
  output does not resemble the shipping product. This is how a team learns to
  ignore a red build.

Cassettes are committed and diff in pull requests. When a prompt changes, the
diff shows exactly how the model's answer changed. That review material is a
benefit, not the maintenance cost it first appears to be.

---

## 6. The synthetic meeting generator

`evals/fixtures/generate.py`, driven by one YAML script per meeting.

```yaml
meeting: quarterly-roadmap
participants:
  - {name: Sarah, role: other}
  - {name: self, is_self: true}
slides:
  - at_ms: 240000
    title: "Q3 Roadmap"
    bullets:
      - "Migrate warehouse - AK - Fri"
      - "Kill legacy API"
      - "Pricing model - AK"
    build: additive
transcript:
  - {at_ms: 255000, track: system, text: "so yeah, these are the priorities"}
  - {at_ms: 262000, track: mic,    text: "who owns the second one?"}
truth:
  keyframes: [...]
  items:
    - {kind: commitment, title: "Migrate warehouse", owner: self, source: slide_only}
```

**Outputs:** `screen.mp4`, `audio_mic.wav`, `audio_system.wav`, `truth.json`.

**Key property: ground truth is derived mechanically from the script, not hand
labelled.** That makes keyframe precision and recall a hard number rather than
an impression, and it lets the adversarial cases from `MVP_SPEC.md` §5.3 be
built by construction instead of hoped for: animated builds, crossfades, a
fast-changing embedded-video span, a gallery-view span with no share active.

**Media is gitignored and regenerated in CI. Only the YAML is committed.** The
repository stays small permanently and fixtures review as text diffs.

**Two fidelities, one source of truth.** Lane B renders the video for real and
cassettes the ASR, so it needs no models. Lane C runs the same scripts through
real TTS and real whisper and measures transcription quality too.

The third bullet in the example above is the flagship test: present on a slide,
never spoken aloud. If `gaps` fails to flag it, the product's central claim is
false, and CI says so on that push.

---

## 7. Eval results contract

```
evals/results/2026-09-11-ollama-qwen2.5-14b.json   one per run, committed
evals/baselines/current.json                        the regression baseline
web/app/evals/page.tsx                              reads results/ at build time
```

Each result file carries `run_id`, `git_sha`, host, provider, model, dataset
identifier, every metric from `MVP_SPEC.md` §7, and a per-meeting breakdown.

**The regression gate and the public marketing page read the same file.** This
is wired in Phase 1, publishing keyframe compression ratio and wall-clock per
meeting-hour, both of which are real numbers available with no LLM in the loop.

### 7.1 Fabrication is two metrics, not one

`MVP_SPEC.md` §7 targets a fabrication rate of 0.00. That number is measured by
two different instruments and reporting one number is dishonest:

| Metric | Method | Coverage | Target |
|---|---|---|---|
| `refs_resolve_and_quote_literal` | deterministic | 100% of items | 1.00 |
| `grounding_accuracy` | sampled judgement | sample | > 0.95 |

Both are published separately.

---

## 8. Security posture

### 8.1 Repository

- `gitleaks` on every push. No secret has ever been committed and none will be.
- **A hard guard that blocks any media file, and any file over 10 MB, from
  entering the repository.** The owner's real meeting recordings must be
  structurally incapable of being committed. This runs in CI and as a local
  pre-commit hook.
- `pip-audit` on every push. Dependabot handles periodic dependency checks
  natively, so no scheduled workflow is needed and none is added.
- A committed lockfile, so a stranger's install is reproducible.
- No secrets in `.env.example`. Copying it produces a working local system.

### 8.2 Product

Restated in `SECURITY.md` and enforced in code:

- Local-first by default. No audio, frames or transcripts leave the machine
  unless `LLM_PROVIDER` is explicitly pointed at a cloud provider.
- No telemetry, ever.
- Capture is scoped to the meeting window and pauses when sharing stops.
- The consent prompt is part of the capture flow from its first commit, not a
  later patch. Recording without disclosure is illegal in two-party-consent
  states and under GDPR.

---

## 9. Install and first-run contract

**The promise: Docker is the only prerequisite.**

```bash
docker compose up -d
make demo
```

`make demo` generates a synthetic meeting and prints the interleaved timeline,
including a slide-only action item. No model downloads, no API keys, no
accounts. It uses the same generator the test suite uses, so it cannot rot
without CI going red.

The README shows the real output and a GIF above the fold, so readers who will
never install anything still understand the product.

**Phase 1 requires no LLM at all.** Ingest, ASR, keyframes and align run with
zero Ollama. The first release is therefore Docker plus one pip install, and
the LLM section of `.env` stays commented out until Phase 2.

---

## 10. Stack amendments

| Component | Was | Now | Reason |
|---|---|---|---|
| ASR default | whisper.cpp compiled binary + manual ggml download | **faster-whisper** | pip installable, no compile step, downloads its own model, word timestamps, good CPU performance |
| OCR | PaddleOCR | **RapidOCR** | same PP-OCR models on ONNXRuntime instead of paddlepaddle, a fraction of the install weight, genuinely cross-platform |

whisper.cpp and WhisperX remain available as opt-in backends behind the same
interface, selected by `ASR_BACKEND`, for users who want Metal acceleration or
forced alignment. **All three are benchmarked on the golden set and published
in the eval table**, which converts an install convenience decision into a
measured result.

These amend `MVP_SPEC.md` §3 and `DECISIONS.md` 0003. New decision entries are
written in Phase 0.

---

## 11. Amendments to MVP_SPEC.md

1. **Extraction uses per-chunk local handles, not database IDs.** §5.7 feeds
   `utterance_id 4412` to the model. A mistyped digit produces a reference that
   resolves to the wrong row, which the existing guard accepts. Chunks present
   sources as `u1..uN` and `k1..kM`, mapped back to database IDs outside the
   model. A typo now fails closed.
2. **Every evidence quote must be a literal substring** of the referenced
   `utterance.text` or `keyframe.ocr_text`. Deterministic, free, runs on 100% of
   items, and catches most of the fabrication class that sampled grounding only
   estimates. Hard gate.
3. **Fabrication is reported as two metrics.** See §7.1.
4. **The keyframe state machine is unit tested with no video.** Frame sequences
   are generated programmatically and fed to the state machine directly. Every
   edge case in §5.3 becomes a named test, with no fixture bytes.
5. **Phase numbering corrected.** §2 says capture is Phase 3; §8 and `CLAUDE.md`
   say Phase 4. Phase 4 is correct.
6. **Phase 2 gains two features:** markdown export of the typed record, and a
   documented OBS recording profile. See §12.

---

## 12. Dogfooding before capture exists

Native capture is Phase 4. The owner does not need to wait for it.

**OBS recording profile.** A documented OBS setup produces mic on track 1,
desktop audio on track 2, and a screen capture, on one hotkey. That is exactly
the two-track input `ingest` expects, and it makes the diarization shortcut in
§5.2 work immediately. Shipped as a profile file plus a one-page setup doc.

**Markdown export.** The typed record renders to one clean markdown file per
meeting: open commitments at the top, then decisions, questions and risks, with
keyframe thumbnails and evidence links inline. Small feature, disproportionate
daily value, and it is the artifact the owner will actually read.

Together these resolve a chicken-and-egg problem in the eval plan: the real
golden-set recordings come from the owner using the tool.

---

## 13. Phases and exit criteria

A phase is complete when its exit criterion is green in CI. Phase N+1 does not
start before then. Each phase gets its own implementation plan, its own branch,
one pull request, a merge, a tag and published numbers.

| Phase | Contents | Exit criterion |
|---|---|---|
| **0** | git init and push, CI lanes A/B/S, security scanning, community files, STATUS.md, deploy.sh, static site skeleton, DECISIONS entries for §4.1 and §10 | a deliberately broken PR goes red and a fixed one goes green; gitleaks and the large-file guard both provably block a test commit |
| **1** | migrations, config, db, models, job runner, ingest, asr, keyframes, align, CLI, synthetic generator, cassette layer | `make demo` prints the interleaved timeline with Docker as the only prerequisite. Keyframe precision and recall >= 0.95 on synthetic. Compression ratio and wall-clock published to `/evals` |
| **2** | LLM providers with failover, ocr, caption, extract, gaps, eval harness, Next.js timeline page, markdown export, OBS profile | `refs_resolve_and_quote_literal` = 1.00. Commitment recall > 0.85, precision > 0.90. **Slide-only recall > 0.70.** Owner begins processing real meetings |
| **3** | ledger, index, pre-meeting brief, cross-meeting search, golden set expanded | a commitment opened in meeting 1 and closed in meeting 3 resolves correctly across a synthetic series. Every brief line cites its meeting and timestamp |
| **4** | macOS capture via ScreenCaptureKit, consent prompt, global hotkey manual frame | capture output feeds `ingest` unchanged. Consent cannot be bypassed. **Requires a macOS runner, added at the start of this phase** |
| **5** | packaging, landing page, public eval table, release | a clean machine installs and runs from the published instructions. Real meeting numbers measured and published |

Windows and Linux capture are out of scope. Phase 4 writes the interface and
leaves `TODO(phase4)` for the other platforms, per hard rule 5.

---

## 14. Open items

- **The GitHub repository URL is not yet known.** Phase 0 cannot push without
  it. Everything else in Phase 0 can proceed.
- **A macOS runner is required before Phase 4** and does not exist. Not
  blocking until then, but it is a real prerequisite.
- **Real golden-set recordings** arrive from the owner's own use during Phase 2.
  Until then every published number is labelled as measured on synthetic data.
