-- Document tags, rolling chat summary, and editable user memory.
alter table documents add column if not exists tags text[] not null default '{}';
alter table chats add column if not exists summary text;
alter table chats add column if not exists summary_upto timestamptz;

create table if not exists user_memory (
    user_id uuid primary key references auth.users (id) on delete cascade,
    content text not null check (length(content) <= 2000),
    updated_at timestamptz not null default now()
);

alter table user_memory enable row level security;
create policy "Users can select their own memory" on user_memory
    for select using (auth.uid() = user_id);
create policy "Users can insert their own memory" on user_memory
    for insert with check (auth.uid() = user_id);
create policy "Users can update their own memory" on user_memory
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "Users can delete their own memory" on user_memory
    for delete using (auth.uid() = user_id);
