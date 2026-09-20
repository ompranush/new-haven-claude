-- Run this once in the Supabase SQL editor (safe to re-run). Tables are RLS-enabled with no policies,
-- so only the service-role key (used server-side on Railway) can read or write them.

create table if not exists metrics  (village text, day integer, data jsonb, primary key (village, day));
create table if not exists events   (id bigserial primary key, village text, day integer, category text, importance real, text text, brain text, actors jsonb, created timestamptz default now());
create table if not exists thoughts (id bigserial primary key, village text, day integer, citizen_id integer, name text, text text, emotion text, source text, created timestamptz default now());
create table if not exists decrees  (id bigserial primary key, village text, day integer, session text, sponsor text, text text, narration text, effects jsonb, created timestamptz default now());
create table if not exists residents(village text, citizen_id integer, name text, sponsor text, provider text, model text, base_url text, enc_key text, max_calls integer, token_hash text, notes text, created timestamptz default now(), primary key (village, citizen_id));
alter table residents add column if not exists token_hash text;
alter table residents add column if not exists notes text;
create table if not exists snapshots(village text primary key, day integer, blob bytea, updated timestamptz default now());
create index if not exists events_village_day on events (village, day desc);
create index if not exists thoughts_village_day on thoughts (village, day desc);
alter table metrics enable row level security;  alter table events enable row level security;  alter table thoughts enable row level security;
alter table decrees enable row level security;  alter table residents enable row level security; alter table snapshots enable row level security;
-- no policies: only the service-role key (server side) can read or write.
