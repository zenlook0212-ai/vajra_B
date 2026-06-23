-- Phase B-lite: pg_trgm for Chinese keyword retrieval (LIKE / similarity).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS canon_chunks_T_text_trgm_idx
  ON canon_chunks_T USING gin (text gin_trgm_ops);
