# Contributing

## Before you start

Read `docs/superpowers/specs/2026-09-11-meetinglens-v0.1-design.md` for what is
being built, and `docs/DECISIONS.md` for why. `docs/MVP_SPEC.md` describes a
larger, suspended plan and is not what is implemented.

## Setup

```bash
make setup
make test
make check
```

## The rules that are not style preferences

1. **No language model in the pipeline.** If an output cannot be derived
   mechanically from the input, it does not belong in this version. The value of
   the tool is that it cannot invent a commitment nobody made.
2. **No media in git, ever.** Every fixture is generated at test time. See
   `tests/video.py`. `scripts/check_no_media.py` enforces it.
3. **Stages are idempotent.** Running one twice must leave the database exactly
   as running it once did, and every stage has a test that proves it.
4. **Decode once, at one frame per second.** Decoding at full frame rate and
   discarding frames is the difference between seconds and twenty minutes.
5. **Milliseconds inside a meeting are `*_ms`. Wall-clock times are `*_at`.**
   Do not mix them.
6. **Migrations are forward-only** and numbered. Do not edit one that has been
   applied.

## Pull requests

`make check` and `make test` must pass. A change to detection thresholds or to
the keyframe algorithm needs a test that pins the behaviour with explicit
numbers, in the style of `tests/test_keyframe_detect.py`, so that a later change
narrowing the margin fails loudly.
