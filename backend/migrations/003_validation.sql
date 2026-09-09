-- Validation hardening: prevent duplicate document names per user (which
-- would otherwise silently double-ingest the same content and double-count
-- it in retrieval), and cap file size at the Storage layer -- the real
-- enforcement point, since uploads go browser -> Storage directly and never
-- pass through this backend.

alter table documents
    add constraint documents_user_id_filename_key unique (user_id, filename);

update storage.buckets
set file_size_limit = 26214400  -- 25 MB, matching the frontend's own cap
where id = 'documents';
