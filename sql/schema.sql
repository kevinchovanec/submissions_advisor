-- Submissions Advisor — Supabase schema
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).

-- ============================================================
-- Tables
-- ============================================================

create table if not exists stories (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users not null,
  slug        text not null,
  title       text not null,
  word_count  integer,
  style       text,
  description text,
  created_at  timestamptz default now(),
  unique (user_id, slug)
);

create table if not exists submissions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users not null,
  story_slug  text not null,
  journal     text not null,
  sub_date    date not null,
  outcome     text not null default 'pending',
  notes       text default '',
  created_at  timestamptz default now()
);

create table if not exists templates (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users not null,
  name        text not null,
  description text default '',
  content     text not null,
  updated_at  timestamptz default now(),
  unique (user_id, name)
);

create table if not exists feedback (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users not null,
  journal       text not null,
  story         text default '',
  feedback_date date,
  feedback_text text not null,
  created_at    timestamptz default now()
);

-- ============================================================
-- Row-level security
-- Users can only read and write their own rows.
-- ============================================================

alter table stories    enable row level security;
alter table submissions enable row level security;
alter table templates  enable row level security;
alter table feedback   enable row level security;

create policy "stories: own rows only"
  on stories for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "submissions: own rows only"
  on submissions for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "templates: own rows only"
  on templates for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "feedback: own rows only"
  on feedback for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- conversations: one row per chat session; messages stored as JSONB
-- api_history (full Claude tool-use array) is NOT stored — client holds it in memory
create table if not exists conversations (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users not null,
  story_slug  text not null,
  started_at  timestamptz default now(),
  messages    jsonb not null default '[]'
);

alter table conversations enable row level security;

create policy "conversations: own rows only"
  on conversations for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ============================================================
-- Account deletion helper
-- Deletes all data rows owned by the calling user.
-- The API also calls auth.admin.delete_user() after this to remove the auth account.
-- ============================================================

create or replace function delete_user_data()
returns void language plpgsql security definer as $$
declare uid uuid := auth.uid();
begin
  delete from conversations where user_id = uid;
  delete from feedback     where user_id = uid;
  delete from templates    where user_id = uid;
  delete from submissions  where user_id = uid;
  delete from stories      where user_id = uid;
end;
$$;
