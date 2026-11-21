-- TruthLens AI persistent investigation storage.
-- Run this in the Supabase SQL Editor. Keep the service-role key server-side only.
create extension if not exists pgcrypto;

create table if not exists public.investigations (
    id uuid primary key default gen_random_uuid(),
    user_key text not null,
    title text not null,
    source_name text not null default '',
    extracted_text text not null default '',
    claims jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists investigations_user_created_idx
    on public.investigations (user_key, created_at desc);

create table if not exists public.evidence (
    id uuid primary key default gen_random_uuid(),
    investigation_id uuid not null references public.investigations(id) on delete cascade,
    user_key text not null,
    claim text not null,
    title text not null default 'Untitled source',
    url text not null default '',
    excerpt text not null,
    relation text not null check (relation in ('Supports','Contradicts','Context only','Unclear')),
    created_at timestamptz not null default now()
);

create index if not exists evidence_investigation_idx
    on public.evidence (investigation_id, created_at desc);

alter table public.investigations enable row level security;
alter table public.evidence enable row level security;

-- The application uses the service-role key only on the server. Do not expose it
-- in client-side code, browser JavaScript, or public repository files.
revoke all on public.investigations from anon, authenticated;
revoke all on public.evidence from anon, authenticated;
grant all on public.investigations to service_role;
grant all on public.evidence to service_role;
