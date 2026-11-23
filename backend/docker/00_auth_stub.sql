-- Local-only stand-in for the Supabase `auth` schema so migrations/001_init.sql
-- (FKs to auth.users, RLS via auth.uid()) can run on a plain pgvector image.
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);
create or replace function auth.uid() returns uuid language sql stable as
$$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
