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

grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
