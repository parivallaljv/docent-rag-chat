-- Enable Realtime change notifications for the documents table. Without
-- this, DocumentList.tsx's postgres_changes subscription connects
-- successfully but never actually receives INSERT/UPDATE/DELETE events --
-- the frontend only ever shows what it fetched on mount, silently missing
-- both a newly-uploaded document appearing and its status updating from
-- pending -> processing -> ready/failed.

alter publication supabase_realtime add table documents;
