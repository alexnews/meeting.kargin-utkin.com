---
name: grounded-extraction
description: Use for any LLM or VLM call that produces structured output — extraction of decisions, commitments, questions and risks, slide captioning, gap detection, or commitment matching. Covers prompt structure, the evidence contract, the reference-validation guard, chunking with overlap, merge logic, and provider abstraction. Trigger whenever writing or debugging a prompt or parsing model output.
---

# Grounded extraction

The product's credibility rests entirely on this: **a fabricated commitment is worse than a missed one.** A user who finds one invented action item stops trusting every item. A user who finds a missing one adds it manually and moves on.

Every quality tradeoff resolves toward saying less.

## The evidence contract

Every extracted item must carry at least one `evidence` reference pointing at a real `utterance.id` or `keyframe.id`.

```json
{
  "kind": "commitment",
  "title": "Send pricing model to Sarah",
  "detail": "Three-tier with usage-based overage",
  "owner": "self",
  "due_date": "2026-09-19",
  "confidence": 0.86,
  "evidence": [
    {"source_type": "utterance", "ref": 4412, "quote": "I'll get you the pricing"},
    {"source_type": "keyframe",  "ref": 87,   "quote": "Pricing model — AK — Fri"}
  ]
}
```

## The validation guard — never skip this

After parsing, before inserting:

1. Resolve every `ref` against the database, **scoped to this meeting**.
2. Drop any item with zero resolvable refs. Log it at WARNING with the item title.
3. For utterance refs, check the `quote` is a substring of that utterance's text after normalizing whitespace and case. If not, drop the evidence row. If that leaves the item with no evidence, drop the item.
4. Check `owner` resolves to `self` or a `meeting_participant`. If not, set `owner_id = NULL` and `needs_review = true` — do not guess.
5. Record the drop rate. A rising drop rate is the earliest signal of prompt or model regression, and it belongs in the eval report.

This mirrors the fact-check pass that made the PodTalk pipeline trustworthy. It is not optional and it is not a nice-to-have.

## Prompt structure

System prompt states the schema, the rules, and the refusal behaviour. User message carries the timeline chunk with IDs attached to every line:

```
[u:4410 00:12:03 OTHER] can you get me the pricing model by Friday
[u:4412 00:12:09 SELF ] yeah I'll get you the pricing
[k:87   00:12:15 SLIDE] Next steps
                        - Pricing model — AK — Fri
                        - Security review — SK
```

Non-negotiable rules to state explicitly in the system prompt:

- Every item MUST cite at least one `u:` or `k:` id from the provided text. No citation means do not emit the item.
- `quote` MUST be copied verbatim from the cited line.
- Never infer a `due_date` that was not stated or displayed. Use null.
- `owner` is `self`, a named participant, or null. Never guess from context alone.
- When uncertain, omit the item. Under-extraction is correct behaviour.

## Chunking and merge

Meetings exceed context and long contexts degrade extraction quality regardless. Chunk the aligned timeline into ~15-minute windows with ~2 minutes of overlap.

The overlap causes duplicates by design. Merge afterwards:

- Two items match if embedding cosine similarity > 0.85 **and** `kind` matches **and** owners are compatible (equal, or one is null).
- On merge: keep the longer `detail`, union the evidence, take the **max** confidence, and prefer a non-null `due_date` and `owner`.
- Never merge across `kind`. A decision and a commitment about the same topic are different rows.

## Slide-only items

The flagship capability. When extracting, treat a bullet that appears in `keyframe.ocr_text` but has no semantically similar utterance in the aligned span as a **real candidate item**, not noise. Emit it with keyframe-only evidence and `needs_review = true`, reason `slide_only`.

This is the case every competing tool loses. Do not filter it out for looking unsupported — the slide *is* the support.

## Provider abstraction

Never import a provider SDK in stage code. Go through `core.llm.base.LLMProvider`:

```python
class LLMProvider(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict | None = None,
        model: str | None = None,
    ) -> LLMResult: ...
```

`LLMResult` carries `text`, `parsed`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`. Those numbers feed the eval report.

Implementations: `ollama` (default), `nim`, `anthropic`, `openai`. Selected by `LLM_PROVIDER` env var, with failover order from config. Every prompt must run on the local provider — if a prompt only works on a frontier model, that is a finding to record in `docs/DECISIONS.md`, not a reason to hard-code a cloud call.

## Parsing

Request structured output where the provider supports it. Where it doesn't, strip markdown fences, parse, and on `JSONDecodeError` retry **once** with the parse error appended to the conversation. After that, fail the chunk and continue with the other chunks — one bad chunk must not lose the whole meeting.

## Changing a prompt

Prompts are code. They live in `core/llm/prompts/` as versioned files, never inline strings. Any prompt change requires an eval run before merge; record the before and after metrics in the commit message.
