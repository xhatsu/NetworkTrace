-- Advisory typed decisions and submitted evidence provenance without L3 mutation.
ALTER TABLE semantic_assessments ADD COLUMN IF NOT EXISTS recommendation String DEFAULT '';
ALTER TABLE semantic_assessments ADD COLUMN IF NOT EXISTS recommendation_confidence Nullable(Float64);
ALTER TABLE semantic_assessments ADD COLUMN IF NOT EXISTS recommendation_probabilities Map(String, Float64);
ALTER TABLE semantic_assessments ADD COLUMN IF NOT EXISTS input_signal_ids Array(String);
