# STATUS

Live state. Not a log. Delete lines that stop being true.

**Version:** v0.1, working end to end. Public at
`github.com/alexnews/meeting.kargin-utkin.com`, CI green on every push.

## What works right now

```bash
make setup
.venv/bin/meetinglens process ~/Downloads/"meeting.mp4" -t ~/Downloads/"meeting.vtt"
```

Writes `~/Documents/MeetingLens/<date>-<slug>/` with a markdown file and its
keyframe images: the transcript interleaved with every slide shown, slide text
quoted, thumbnails inline, real speaker names, and the user marked as `(you)`.

Pipeline: `ingest -> keyframes -> transcript -> ocr -> export`. No language model
anywhere. 57 tests, ruff clean, mypy strict clean.

Measured on a generated three minute 720p recording with ten topics, each with
an animated build: 4.7 s end to end, 10 of 10 slides found, builds collapsed to
their finished state.

## Blocked on the owner

- **Run it on one real Teams recording.** This is the only thing that matters
  now. Every number above comes from generated fixtures. Two thresholds are
  expected to need tuning against real video, and both are environment
  variables, so tuning costs nothing: `MEETINGLENS_DHASH_THRESHOLD` (default 24)
  and `MEETINGLENS_OCR_MIN_COVERAGE` (default 0.015).
- **Check whether your Teams tenant produces transcripts.** Open a past
  recording in OneDrive or the meeting chat and look for a `.vtt` download. If
  it is missing, the faster-whisper fallback installs with the `asr` extra and
  costs a model download plus the speaker names.

## Known gaps

- Thresholds are calibrated on synthetic slides only. Real Teams recordings
  composite participant thumbnails over shared content, which has never been
  tested here.
- Teams recordings are 1080p and longer; only 720p and three minutes have been
  measured.
- There is no `meetinglens list` or `meetinglens open`. One meeting, one command.
- The faster-whisper fallback path has never been executed. It is wired and its
  failure mode is tested, but no meeting has been transcribed with it.

## Decided, do not relitigate

- **No language model in v0.1.** The tool must be incapable of fabricating.
- **SQLite, not Postgres.** One file, no Docker. Deliberately breaks the
  cross-project Postgres convention because install simplicity wins here.
- **Teams-native recording only.** It announces itself to participants, which is
  how consent should work. No silent third-party recorder.
- **GitHub-hosted CI while the repository is public.** Free, and a stranger's
  pull request runs in a throwaway VM rather than on a machine we own. If the
  repository ever goes private, workflows move to self-hosted in that commit.
- **No media in git, ever.** Fixtures are generated at test time and
  `scripts/check_no_media.py` fails the build otherwise.

## Suspended, not cancelled

`docs/MVP_SPEC.md` holds the larger plan: typed extraction of decisions and
commitments, gap detection, a cross-meeting commitment ledger, a pre-meeting
brief. `docs/superpowers/specs/2026-09-11-meetinglens-delivery-design.md` holds
its evaluation design, grounding contract and fabrication metrics. Revisit only
after v0.1 has been in daily use for a month.
