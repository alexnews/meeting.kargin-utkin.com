# MeetingLens

Turn a Microsoft Teams recording into one markdown file: the transcript
interleaved with every slide that was on screen, each slide's text extracted,
thumbnails inline, real speaker names.

Action items very often live on a slide and are never spoken aloud. Someone
shares a list of five deliverables and says "yeah, so, these". A transcript-only
tool loses all of it.

**There is no language model anywhere in this.** Every line of the output is a
mechanical transformation of the input, so it cannot invent a commitment that
nobody made.

## What it produces

```markdown
# weekly sync

2026-09-12 | 47 min | 2 slides | 4 turns

## Timeline

### `00:00` Q3 Roadmap

![Q3 Roadmap](keyframes/0000.webp)

> Q3 Roadmap
> 1. Migrate warehouse
> 2. Kill legacy API
> 3. Pricing model - AK - Fri
> 4. Hire two engineers

**`00:01` Alex Kargin (you):** Let us start with the roadmap for the quarter.

**`00:06` Sarah Chen:** So yeah, these are the priorities.

### `00:09` Revenue
...
```

Line three of that slide, `Pricing model - AK - Fri`, was never said out loud.
That is the whole point.

## Install

One command. No Docker, no database server, no Homebrew. ffmpeg ships inside the
wheel and the OCR models ship with it, so a first run downloads nothing.

```bash
uv tool install git+https://github.com/alexnews/meeting.kargin-utkin.com
```

## Use

```bash
meetinglens process ~/Downloads/"weekly sync.mp4" -t ~/Downloads/"weekly sync.vtt"
```

That writes `~/Documents/MeetingLens/2026-09-12-weekly-sync/` containing the
markdown file and its images. Open it in Obsidian, or anything that reads
markdown.

### Getting the two files out of Teams

1. Record the meeting in Teams, with transcription on.
2. Afterwards, open the meeting chat or the recording in OneDrive.
3. Download the `.mp4`, and download the transcript as `.vtt`.

Teams announces the recording to everybody in the call, which is how consent is
meant to work. Do not run a silent third-party recorder at work instead.

**No transcript?** It still works. Install the fallback with
`uv tool install "meetinglens[asr] @ git+https://github.com/alexnews/meeting.kargin-utkin.com"`
and the audio is transcribed locally with faster-whisper. That costs a model
download and you lose the speaker names.

### Marking which voice is yours

```bash
export MEETINGLENS_SELF_NAME="Alex Kargin"   # exactly as Teams writes it
```

Your lines then read `Alex Kargin (you):`.

## How it works

```
ingest -> keyframes -> transcript -> ocr -> export
```

The interesting part is `keyframes`. Video is decoded **once**, at one frame per
second, straight to small grayscale frames through a pipe. Each frame gets a
24x24 difference hash, and a new keyframe is committed only when the screen has
held still for two seconds, which discards crossfades and mid-transition frames.

Two rules then decide what survives, both applied after text extraction rather
than on pixel statistics, because it is simpler and works better:

- **Text density.** A frame with almost no text is worthless as a note. One
  threshold removes gallery view, the idle desktop and video playback at once.
  It is also the privacy control: frames of people's faces never reach a
  document.
- **Superset merge.** If a frame's text contains the previous frame's text, the
  earlier one was a slide still building. It is dropped and the later frame
  takes over its span.

Dropped frames are marked, not deleted, so thresholds can be retuned and the
export rebuilt without touching the video again.

### Measured

On an M-series Mac, against a generated three minute 720p recording with ten
topics, each with an animated build:

| | |
|---|---|
| End to end | **4.7 s** for 3 minutes of video |
| Slides found | 10 of 10, builds collapsed to their finished state |
| OCR | about 0.3 s per slide |

An hour of real 1080p video should land in the low minutes. Expect roughly
thirty images and a few megabytes out of a recording measured in gigabytes.

Two numbers worth knowing, because they were surprises. The textbook 64-bit
difference hash **cannot tell slides apart**: measured on rendered slides,
adding a bullet moved 3 bits while a completely different slide moved 7. Hashing
at 24x24 gives 12 against 38. And the comparison has to be anchored on the most
recent frame, not on the frame a keyframe opened with, or a slide that builds
drifts far enough that the next slide looks like its own stale opening state.
Both are pinned by tests. See `docs/DECISIONS.md`.

## What it does not do

Deliberately, for now: no summarisation, no extracted action items, no language
model, no live capture, no web interface, no cloud. It reads recordings you
already have and writes a file you already know how to read.

## Privacy

Everything runs on your machine. Nothing is uploaded, there is no account, and
there is no telemetry. The database is one SQLite file in `~/.meetinglens/`.

Screen recordings see more than audio ever did: Slack messages, password
managers, other people's confidential material. The text density rule means
frames without meaningful text are never written to an export, but read
`SECURITY.md` before pointing this at anything sensitive.

## Development

```bash
make setup    # venv and editable install
make test     # 57 tests
make check    # ruff and mypy strict
```

No media file is ever committed. Every test fixture, including encoded video, is
generated at test time; `scripts/check_no_media.py` fails the build if a
recording or anything over 10 MB is staged.

- `docs/superpowers/specs/2026-09-11-meetinglens-v0.1-design.md` is the design.
- `docs/DECISIONS.md` is why things are the way they are.
- `docs/MVP_SPEC.md` is a larger, suspended plan. It is not what is built.

## License

MIT.
