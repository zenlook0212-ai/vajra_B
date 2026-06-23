CREATE INDEX IF NOT EXISTS canon_chunks_T_embedding_hnsw ON canon_chunks_T
  USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS canon_chunks_T_tsv_gin ON canon_chunks_T USING gin (tsv);
