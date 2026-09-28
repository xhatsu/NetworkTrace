-- Preserve Jev's typed choice distributions and OpenRouter usage accounting.
ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS provider_request_id String DEFAULT '' AFTER provider_model;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS category_confidence Nullable(Float32) AFTER category;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS category_probabilities Map(String, Float32) AFTER category_confidence;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS priority_confidence Nullable(Float32) AFTER priority;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS priority_probabilities Map(String, Float32) AFTER priority_confidence;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS input_tokens UInt32 AFTER response_digest;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS output_tokens UInt32 AFTER input_tokens;

ALTER TABLE semantic_assessments
    ADD COLUMN IF NOT EXISTS cost_usd Nullable(Float64) AFTER output_tokens;
