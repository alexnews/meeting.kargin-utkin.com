---
name: db-migration
description: Use for any change to the PostgreSQL schema — new tables, columns, indexes, pgvector changes, or backfills. Covers the forward-only numbering convention, the ms-versus-timestamptz rule, embedding and HNSW index conventions, and safe backfill patterns. Trigger on any mention of migrations, schema, DDL, or adding a column.
---

# Migrations

Forward-only, numbered SQL in `migrations/`. Applied with `make migrate`.

## Rules

1. **Never edit an applied migration.** Not even a typo in a comment. Write a new one.
2. **File naming:** `NNNN_short_name.sql`, zero-padded to four digits, sequential. `0003_add_commitment_status.sql`.
3. **One logical change per file.** A new table plus its indexes is one change. A new table plus an unrelated column is two files.
4. **Every migration is wrapped in a transaction** except ones that create indexes concurrently. Say which in a header comment.
5. **No ORM-generated migrations.** Hand-written SQL. This is a data engineering project; the schema is the design document and it should read like one.

## Header comment

Every file starts with why, not what. The DDL already says what.

```sql
-- 0007_keyframe_kind.sql
-- Embedded video playback floods the keyframe table. Adding `kind` so the
-- rate-limited video spans can be excluded from extraction input without
-- deleting them (we still want them for the UI timeline).
```

## Time columns — the rule that will otherwise bite

- **Offsets inside a meeting** are integer milliseconds from meeting start. Name them `*_ms`. Type `INTEGER`.
- **Wall-clock** is `TIMESTAMPTZ`. Name them `*_at`.

Never store a meeting offset as an interval, a float of seconds, or a timestamp. Never name a wall-clock column `*_ms`. Alignment between transcript and keyframes is the core of the product and it breaks silently when units are mixed.

## Embeddings

- Column is always named `embedding`, type `vector(768)`, nullable.
- Index is always HNSW with `vector_cosine_ops`. Not IVFFlat — the tables are small and HNSW needs no training step.
- Embeddings are written by the `index` stage, never by the stage that creates the row. A new embedding column means a backfill migration plus an `index` stage change.
- If the embedding model changes, the dimension probably changes. That is a new column and a full backfill, not an in-place alter.

## Cascades

Everything hangs off `meeting`. Deleting a meeting must delete its utterances, keyframes, items, evidence, and jobs — use `ON DELETE CASCADE` on the `meeting_id` foreign key.

**Exception:** `commitment` rows survive. They reference `item(id)` without cascade, because a commitment may be referenced by later meetings that closed it. Deleting a meeting that opened a still-open commitment should fail loudly rather than silently orphan the ledger. Handle that case explicitly in application code.

## Backfills

Never backfill in the same migration that adds the column when the table can be large. Pattern:

1. Migration adds the column, nullable, no default.
2. A script in `scripts/backfill_NNNN.py` fills it in batches.
3. A later migration adds `NOT NULL` once the backfill has run.

A `DEFAULT` on `ALTER TABLE ADD COLUMN` is fine for constants on small tables, and is not fine for anything computed.

## Testing

`make migrate` against a fresh database must succeed from `0001` to head with no errors. CI runs this on every commit. If it does not pass, nothing else matters — the schema is the spine.

Also verify: `make migrate` twice in a row is a no-op, not an error.
