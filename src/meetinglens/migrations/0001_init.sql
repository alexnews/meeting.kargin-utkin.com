-- v0.1 schema. SQLite. Forward-only.
-- Timestamps inside a meeting are integer milliseconds (*_ms).
-- Wall-clock times are ISO 8601 text (*_at).

CREATE TABLE meeting (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    transcript_path TEXT,
    started_at      TEXT,
    duration_ms     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE speaker (
    id           INTEGER PRIMARY KEY,
    meeting_id   INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    is_self      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (meeting_id, display_name)
);

CREATE TABLE utterance (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms   INTEGER NOT NULL,
    end_ms     INTEGER NOT NULL,
    speaker_id INTEGER REFERENCES speaker(id),
    text       TEXT NOT NULL,
    source     TEXT NOT NULL CHECK (source IN ('vtt', 'asr'))
);
CREATE INDEX utterance_meeting_start ON utterance (meeting_id, start_ms);

CREATE TABLE keyframe (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    start_ms    INTEGER NOT NULL,
    end_ms      INTEGER NOT NULL,
    image_path  TEXT NOT NULL,
    dhash       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'slide',
    ocr_text    TEXT,
    dropped     INTEGER NOT NULL DEFAULT 0,
    drop_reason TEXT
    -- Deliberately no UNIQUE on (meeting_id, start_ms). When the superset pass
    -- collapses a slide build, the surviving frame takes over the dropped
    -- frame's span, so two rows share a start_ms until one of them is marked
    -- dropped. Dropped rows are kept so a threshold can be retuned.
);
CREATE INDEX keyframe_meeting_start ON keyframe (meeting_id, start_ms);

CREATE TABLE job (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    UNIQUE (meeting_id, stage)
);
