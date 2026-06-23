-- CBETA canon RAG schema (方案 B)
-- Note: pgvector HNSW on `vector` is capped at 2000 dims; we use halfvec(2048).

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS semantic_cache CASCADE;
DROP TABLE IF EXISTS ingest_progress CASCADE;
DROP TABLE IF EXISTS canon_chunks CASCADE;

CREATE TABLE canon_chunks (
  id           BIGSERIAL,
  series       CHAR(2) NOT NULL,
  canon_id     TEXT NOT NULL,
  coord_start  TEXT NOT NULL,
  coord_end    TEXT NOT NULL,
  text         TEXT NOT NULL,
  char_len     INT NOT NULL,
  file_path    TEXT NOT NULL,
  embedding    halfvec(2048),
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
  PRIMARY KEY (id, series)
) PARTITION BY LIST (series);

CREATE TABLE canon_chunks_T PARTITION OF canon_chunks
  FOR VALUES IN ('T');

CREATE TABLE ingest_progress (
  file_path    TEXT PRIMARY KEY,
  last_coord   TEXT NOT NULL DEFAULT '',
  chunk_count  INT NOT NULL DEFAULT 0,
  completed    BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE semantic_cache (
  query_hash   TEXT PRIMARY KEY,
  query_embed  halfvec(2048),
  top_chunks   JSONB NOT NULL DEFAULT '[]'::jsonb,
  answer       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX canon_chunks_T_canon_id_idx ON canon_chunks_T (canon_id);
CREATE INDEX canon_chunks_T_file_path_idx ON canon_chunks_T (file_path);
CREATE INDEX semantic_cache_created_at_idx ON semantic_cache (created_at);
