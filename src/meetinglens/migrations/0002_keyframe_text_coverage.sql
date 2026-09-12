-- How much of the frame is covered by text, from the OCR boxes.
-- Recorded on every keyframe so the drop thresholds can be calibrated against
-- real recordings without re-decoding video.
ALTER TABLE keyframe ADD COLUMN text_coverage REAL;
