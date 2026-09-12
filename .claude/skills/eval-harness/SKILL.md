---
name: eval-harness
description: Use when adding golden fixtures, adding or changing metrics, or evaluating a prompt, model, or algorithm change. Covers the golden set format, the metric definitions and targets, matching rules for comparing predictions to labels, and the rule that quality changes require an eval run. Trigger on any mention of evals, accuracy, precision, recall, benchmarking, or comparing models.
---

# Eval harness

Build this in Phase 1 with three meetings. Do not defer it to the end.

Two reasons. Practically: without it, every prompt change is a vibe check and quality drifts invisibly. Strategically: the eval table is the most credible artifact in the whole project, and it is the thing an interviewer will actually ask about.

## Golden set

`evals/golden/<meeting_slug>/`:

```
meeting.yaml        # metadata, participants, media paths
labels.yaml         # ground truth, hand-written
media/              # audio + video, or a pointer if too large for git
```

`labels.yaml` holds the true items:

```yaml
commitments:
  - title: Send pricing model to Sarah
    owner: self
    due_date: 2026-09-19
    source: spoken          # spoken | slide_only | both
decisions:
  - title: Postpone the warehouse migration to Q4
    source: spoken
open_questions:
  - title: Who owns the legacy API deprecation
```

Ten meetings is the Phase 3 target. Composition matters more than count — deliberately include:

- At least **two with slide-only action items** (on a slide, never spoken). This is the differentiating capability and it must be measured.
- One with a **heavy accent or heavy cross-talk**.
- One with an **embedded video** playing during screen share.
- One with **no screen share at all** (audio only).
- One **very short** meeting (under 10 minutes) — short-input edge cases break chunking.

Do not commit real recordings of real people to a public repo. Use your own recordings, recordings with explicit consent, or synthetic ones.

## Metrics and targets

| Metric | Target | Definition |
|---|---|---|
| Commitment recall | > 0.85 | matched labels / total labels |
| Commitment precision | > 0.90 | matched predictions / total predictions |
| **Fabrication rate** | **0.00** | items whose evidence refs don't resolve or whose quote isn't in the cited source |
| Grounding accuracy | > 0.95 | sampled manual check that cited evidence actually supports the claim |
| Slide-only recall | > 0.70 | recall restricted to labels with `source: slide_only` |
| Keyframe compression | report | raw video bytes / stored keyframe bytes |
| Cost per meeting-hour | report | sum of `LLMResult.cost_usd` |
| Wall-clock per meeting-hour | report | end-to-end pipeline duration |

**Fabrication rate is a hard gate.** Any non-zero value fails the run regardless of other numbers. Everything else is a target to track, not a gate.

Report the last four always, even though they have no target. A model that hits recall 0.9 at forty times the cost is a different product decision than one at 0.85, and you cannot make that call without the numbers.

## Matching predictions to labels

Automated matching is itself fallible, so keep it conservative and explicit:

- A prediction matches a label if `kind` is equal **and** embedding cosine similarity of the titles > 0.80.
- Greedy matching by descending similarity, one-to-one. A label matches at most one prediction.
- `owner` and `due_date` mismatches do **not** break the match — they are reported separately as `owner_accuracy` and `date_accuracy`. Otherwise one wrong date destroys a recall number and hides what actually changed.

## Running

```
make eval                    # full golden set, current config
make eval MEETING=acme_q3    # single meeting, for fast iteration
make eval PROVIDER=ollama    # override provider
```

Prints a table, writes `evals/results/<timestamp>.json`. Results are committed — the history of the numbers is part of the story.

## When an eval run is required

Any change to: a prompt, the extraction schema, the chunk size or overlap, the merge thresholds, the keyframe change-detection thresholds, the embedding model, or the default provider.

Put before-and-after numbers in the commit message. A change that improves one metric and silently degrades another is the normal case, not the exception.

## Comparing models

Run the same golden set across providers and keep the table. This is how the local-versus-cloud question gets answered with evidence instead of opinion, and it is directly publishable.

```
make eval PROVIDER=ollama MODEL=qwen2.5:14b
make eval PROVIDER=anthropic MODEL=claude-sonnet-4-6
```

Never tune thresholds against the golden set until targets are hit — that is fitting to ten meetings. If a threshold needs tuning, hold out three meetings, tune on seven, report on the held-out three.
