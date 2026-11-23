-- Thumbs up/down on assistant answers (feeds the eval set).
create table if not exists message_feedback (
    message_id uuid not null references messages (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    rating smallint not null check (rating in (-1, 1)),
    comment text check (comment is null or length(comment) <= 1000),
    created_at timestamptz not null default now(),
    primary key (message_id, user_id)
);

alter table message_feedback enable row level security;

create policy "Users can select their own feedback" on message_feedback
    for select using (auth.uid() = user_id);
create policy "Users can insert their own feedback" on message_feedback
    for insert with check (auth.uid() = user_id);
create policy "Users can update their own feedback" on message_feedback
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "Users can delete their own feedback" on message_feedback
    for delete using (auth.uid() = user_id);
