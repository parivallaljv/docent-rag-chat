-- Storage bucket + per-user access policies for uploaded documents.
--
-- The frontend uploads files directly to Supabase Storage (browser ->
-- Supabase, not proxied through this backend) under a `${user_id}/${filename}`
-- path, so Storage's own Row Level Security -- not this API -- is the
-- authorization boundary for uploads/reads of the raw files. This mirrors
-- the pattern already used for the `documents`/`chunks` tables in
-- 001_init.sql, scoped by folder name instead of a `user_id` column since
-- storage.objects has no such column.

insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

create policy "Users can upload to their own folder"
    on storage.objects for insert
    with check (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "Users can read their own files"
    on storage.objects for select
    using (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "Users can update their own files"
    on storage.objects for update
    using (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "Users can delete their own files"
    on storage.objects for delete
    using (
        bucket_id = 'documents'
        and (storage.foldername(name))[1] = auth.uid()::text
    );
