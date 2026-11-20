-- Full-text search column for hybrid retrieval (HYBRID_SEARCH=true).
-- A generated column back-fills existing rows and stays in sync on insert.
alter table chunks
    add column if not exists content_tsv tsvector
    generated always as (to_tsvector('english', content)) stored;

create index if not exists idx_chunks_content_tsv
    on chunks using gin (content_tsv);
