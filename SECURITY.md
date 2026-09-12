# Security

Two separate things live here: how to report a flaw in the software, and what
the software itself exposes you to. The second matters more.

## Reporting a vulnerability

Open a private security advisory through GitHub on this repository. Please do
not open a public issue for anything exploitable.

## What this tool handles

MeetingLens reads meeting recordings. A screen recording is not like an audio
recording: it captures whatever was visible, which routinely includes messages,
password manager windows, unreleased material and other people's confidential
information. Somebody sharing their whole screen instead of one window has
handed the recording far more than they meant to.

Treat every recording you process as if it were the most sensitive thing
visible in it, because it is.

### What the tool does with it

- **Everything runs locally.** No network calls, no account, no telemetry, no
  cloud service. The tool works with the network turned off.
- **Storage is a SQLite file** at `~/.meetinglens/meetinglens.db`, plus keyframe
  images under `~/.meetinglens/storage/`. Both are readable by anything running
  as you. Neither is encrypted.
- **Exports go to `~/Documents/MeetingLens/`** by default, as plain markdown and
  images. If that directory syncs to a cloud drive, your meeting contents sync
  with it. Check.
- **Frames without meaningful text are dropped** before export. That is a
  deliberate privacy control as much as a quality one: gallery view, the idle
  desktop and video playback never reach a document, so faces are not written
  out. It is a heuristic, not a guarantee. Read what you export before sharing
  it.
- **Nothing is deleted for you.** Removing a meeting means deleting its rows and
  its files yourself.

### Recording and consent

Record through Teams, which announces the recording to every participant. That
is the point: consent is part of the flow rather than an afterthought.

Do not run a silent third-party recorder to work around a tenant that has
recording disabled. Recording people without disclosure is illegal in
two-party-consent jurisdictions and under GDPR, and at work it is usually also a
disciplinary matter.

## Repository

No secret has ever been committed and none should be. Every push runs a secret
scan, plus a guard that refuses any committed media file or any file over 10 MB,
so a real recording cannot reach this public repository by accident.
