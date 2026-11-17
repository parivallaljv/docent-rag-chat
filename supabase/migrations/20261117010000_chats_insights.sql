-- Persistent conversations + cached document insights (summary / key facts / quiz).

create table if not exists chats (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_chats_user_updated on chats (user_id, updated_at desc);

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references chats (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    citations jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_messages_chat_created on messages (chat_id, created_at);

create table if not exists document_insights (
    document_id uuid not null references documents (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    kind text not null check (kind in ('summary', 'key_facts', 'quiz')),
    result jsonb not null,
    created_at timestamptz not null default now(),
    primary key (document_id, kind)
);

alter table chats enable row level security;
alter table messages enable row level security;
alter table document_insights enable row level security;

create policy "Users can select their own chats" on chats for select using (auth.uid() = user_id);
create policy "Users can insert their own chats" on chats for insert with check (auth.uid() = user_id);
create policy "Users can update their own chats" on chats for update
    using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "Users can delete their own chats" on chats for delete using (auth.uid() = user_id);

create policy "Users can select their own messages" on messages for select using (auth.uid() = user_id);
create policy "Users can insert their own messages" on messages for insert with check (auth.uid() = user_id);
create policy "Users can delete their own messages" on messages for delete using (auth.uid() = user_id);

create policy "Users can select their own insights" on document_insights for select using (auth.uid() = user_id);
