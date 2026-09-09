-- Initial schema for the RAG chat backend: documents + chunks, pgvector,
-- and Row Level Security scoped to auth.uid().
--
-- Run this once against your Supabase project's Postgres database (SQL
-- Editor, or `psql`/a migration tool pointed at SUPABASE_DB_URL).
--
-- NOTE on RLS vs. this backend: FastAPI connects to Postgres directly via
-- asyncpg using SUPABASE_DB_URL, which authenticates as a superuser-ish
-- role (e.g. `postgres`) that BYPASSES row level security entirely. In this
-- backend, user-scoping is actually enforced in application code (every
-- query in app/db/queries.py filters `WHERE user_id = $1`). The RLS
-- policies below are still worth enabling as defense-in-depth, and become
-- the *real* authorization boundary the moment this schema is ever queried
-- directly by a Supabase client (supabase-js/supabase-py) using a user's own
-- JWT instead of going through this API.

create extension if not exists vector;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    filename text not null,
    storage_path text not null,
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'ready', 'failed')),
    error_message text,
    created_at timestamptz not null default now()
);

create index if not exists idx_documents_user_id on documents (user_id);

create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    page_number int not null,
    chunk_index int not null,
    content text not null,
    embedding vector(768) not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_chunks_document_id on chunks (document_id);
create index if not exists idx_chunks_user_id on chunks (user_id);

-- Approximate nearest-neighbor index for cosine-distance kNN search
-- (the `<=>` operator used in db.queries.search_chunks).
create index if not exists idx_chunks_embedding_hnsw
    on chunks using hnsw (embedding vector_cosine_ops);

-- --- Row Level Security ---

alter table documents enable row level security;
alter table chunks enable row level security;

create policy "Users can select their own documents"
    on documents for select
    using (auth.uid() = user_id);

create policy "Users can insert their own documents"
    on documents for insert
    with check (auth.uid() = user_id);

create policy "Users can update their own documents"
    on documents for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can delete their own documents"
    on documents for delete
    using (auth.uid() = user_id);

create policy "Users can select their own chunks"
    on chunks for select
    using (auth.uid() = user_id);

create policy "Users can insert their own chunks"
    on chunks for insert
    with check (auth.uid() = user_id);

create policy "Users can update their own chunks"
    on chunks for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can delete their own chunks"
    on chunks for delete
    using (auth.uid() = user_id);
