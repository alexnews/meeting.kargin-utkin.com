-- 0001_init.sql
-- Initial schema. The spine of the project: meetings, dual-track transcript,
-- deduplicated keyframes, typed items with mandatory evidence, and the
-- cross-meeting commitment ledger.
--
-- Convention: offsets inside a meeting are integer milliseconds (*_ms).
-- Wall-clock is TIMESTAMPTZ (*_at). Never mix them.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- ============ core ============

CREATE TABLE meeting (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    duration_s      INTEGER,
    source          TEXT NOT NULL DEFAULT 'upload',   -- upload | capture
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|done|failed
    audio_path      TEXT,
    video_path      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE person (
    id              BIGSERIAL PRIMARY KEY,
    display_name    TEXT NOT NULL,
    email           TEXT UNIQUE,
    org             TEXT,
    is_self         BOOLEAN NOT NULL DEFAULT false,
    aliases         TEXT[] DEFAULT '{}',              -- name variants heard in transcripts
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meeting_participant (
    meeting_id      BIGINT REFERENCES meeting(id) ON DELETE CASCADE,
    person_id       BIGINT REFERENCES person(id),
    PRIMARY KEY (meeting_id, person_id)
);

-- ============ transcript ============

CREATE TABLE utterance (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    track           TEXT NOT NULL,        -- 'mic' | 'system'
    speaker_id      BIGINT REFERENCES person(id),
    speaker_label   TEXT,                 -- raw label before resolution
    text            TEXT NOT NULL,
    confidence      REAL,
    embedding       vector(768)
);
CREATE INDEX ON utterance (meeting_id, start_ms);
CREATE INDEX ON utterance USING hnsw (embedding vector_cosine_ops);

-- ============ visual ============

CREATE TABLE keyframe (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,     -- when this visual state appeared
    end_ms          INTEGER NOT NULL,     -- when it was replaced
    image_path      TEXT NOT NULL,        -- WebP q80
    dhash           BIT(64) NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'slide',  -- slide|document|code|video_segment|manual
    is_manual       BOOLEAN NOT NULL DEFAULT false, -- user pressed the hotkey
    ocr_text        TEXT,
    caption         TEXT,                 -- VLM description
    embedding       vector(768)           -- over ocr_text || caption
);
CREATE INDEX ON keyframe (meeting_id, start_ms);
CREATE INDEX ON keyframe USING hnsw (embedding vector_cosine_ops);

-- ============ typed extraction ============

CREATE TABLE item (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,        -- decision|commitment|open_question|risk|topic
    title           TEXT NOT NULL,
    detail          TEXT,
    owner_id        BIGINT REFERENCES person(id),
    due_date        DATE,
    confidence      REAL NOT NULL,
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    review_reason   TEXT,                 -- why gap detection flagged it
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON item (meeting_id, kind);
CREATE INDEX ON item USING hnsw (embedding vector_cosine_ops);

-- every extracted field must point back at its source
CREATE TABLE evidence (
    id              BIGSERIAL PRIMARY KEY,
    item_id         BIGINT NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,        -- 'utterance' | 'keyframe'
    utterance_id    BIGINT REFERENCES utterance(id),
    keyframe_id     BIGINT REFERENCES keyframe(id),
    quote           TEXT,                 -- short supporting span
    CHECK (
        (source_type = 'utterance' AND utterance_id IS NOT NULL) OR
        (source_type = 'keyframe'  AND keyframe_id  IS NOT NULL)
    )
);

-- ============ cross-meeting ledger ============

CREATE TABLE commitment (
    id              BIGSERIAL PRIMARY KEY,
    item_id         BIGINT NOT NULL REFERENCES item(id),
    owner_id        BIGINT REFERENCES person(id),
    counterparty_id BIGINT REFERENCES person(id),
    status          TEXT NOT NULL DEFAULT 'open',  -- open|done|dropped|superseded
    due_date        DATE,
    opened_meeting  BIGINT REFERENCES meeting(id),
    closed_meeting  BIGINT REFERENCES meeting(id),
    closed_reason   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON commitment (owner_id, status);
CREATE INDEX ON commitment (counterparty_id, status);

-- ============ jobs ============

CREATE TABLE job (
    id              BIGSERIAL PRIMARY KEY,
    meeting_id      BIGINT REFERENCES meeting(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

COMMIT;
