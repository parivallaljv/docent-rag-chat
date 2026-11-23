-- Per-turn usage/cost accounting (approximate token counts).
create table if not exists usage_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    kind text not null default 'chat',
    model text,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    cost_usd numeric(12, 6) not null default 0,
    created_at timestamptz not null default now()
);
create index if not exists idx_usage_user_created on usage_events (user_id, created_at desc);

alter table usage_events enable row level security;
create policy "Users can select their own usage" on usage_events
    for select using (auth.uid() = user_id);
