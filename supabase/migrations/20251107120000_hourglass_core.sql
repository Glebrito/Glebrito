-- Colih / Congregação Planalto Natal — Hourglass scheduling persistence
-- Projeto: https://xvriolmnmuezzarpwvwn.supabase.co (sa-east-1)

create extension if not exists "pgcrypto";

-- Congregação / grupo de idioma
create table if not exists public.congregations (
  id uuid primary key default gen_random_uuid(),
  lgroup integer not null unique,
  name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.congregations (lgroup, name)
values (43741, 'Congregação Planalto Natal RN')
on conflict (lgroup) do nothing;

-- Publicadores
create table if not exists public.members (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  hourglass_user_id bigint not null,
  display_name text not null,
  sex text check (sex in ('Male', 'Female', 'Unknown') or sex is null),
  privileges jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (congregation_id, hourglass_user_id)
);

create index if not exists idx_members_congregation on public.members (congregation_id);
create index if not exists idx_members_sex on public.members (sex) where sex is not null;

-- Histórico de designações (uma linha por semana + categoria + pessoa)
create table if not exists public.assignment_history (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  member_id uuid references public.members (id) on delete set null,
  hourglass_user_id bigint,
  week_date date not null,
  role_category text not null,
  assignee_name text,
  source text not null default 'hourglass',
  raw jsonb,
  created_at timestamptz not null default now(),
  unique (congregation_id, week_date, role_category, hourglass_user_id)
);

create index if not exists idx_assignment_history_week on public.assignment_history (congregation_id, week_date);
create index if not exists idx_assignment_history_member on public.assignment_history (member_id, role_category);
create index if not exists idx_assignment_history_category on public.assignment_history (congregation_id, role_category);

-- Programa + schedule crus por semana (auditoria / reprocessamento)
create table if not exists public.meeting_programs (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  week_date date not null,
  meeting_json jsonb,
  schedule_json jsonb,
  synced_at timestamptz not null default now(),
  unique (congregation_id, week_date)
);

-- Regras de negócio (JSON por chave)
create table if not exists public.rules_config (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  rule_key text not null,
  rule_value jsonb not null,
  description text,
  updated_at timestamptz not null default now(),
  unique (congregation_id, rule_key)
);

-- Espaçamento mínimo entre designações
create table if not exists public.spacing_constraints (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  constraint_kind text not null check (
    constraint_kind in ('same_role', 'any_sister_fm', 'global_role')
  ),
  role_category text,
  min_weeks integer not null default 2 check (min_weeks >= 0),
  active boolean not null default true,
  notes text,
  unique nulls not distinct (congregation_id, constraint_kind, role_category)
);

-- Execuções de sync
create table if not exists public.sync_runs (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'failed', 'partial')),
  source text not null default 'hourglass_api',
  stats jsonb not null default '{}'::jsonb,
  error_message text
);

-- Sugestões / rascunhos antes de publicar no Hourglass
create table if not exists public.draft_assignments (
  id uuid primary key default gen_random_uuid(),
  congregation_id uuid not null references public.congregations (id) on delete cascade,
  week_date date not null,
  role_category text not null,
  member_id uuid references public.members (id) on delete set null,
  hourglass_user_id bigint,
  display_name text,
  status text not null default 'draft' check (status in ('draft', 'approved', 'exported', 'applied', 'rejected')),
  suggestion_run_id uuid,
  rationale jsonb not null default '{}'::jsonb,
  patch_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (congregation_id, week_date, role_category)
);

create index if not exists idx_draft_assignments_week on public.draft_assignments (congregation_id, week_date);

-- Valores padrão Planalto (irmãs em Aplique-se reunião 4–6 → apply1–3)
insert into public.rules_config (congregation_id, rule_key, rule_value, description)
select c.id, 'sisters_only_categories', '["apply1","apply2","apply3","apply1_assistant","apply2_assistant","apply3_assistant"]'::jsonb,
       'Partes 4–6 da reunião (slots FM 1–3): apenas irmãs (estudante e assistente)'
from public.congregations c where c.lgroup = 43741
on conflict (congregation_id, rule_key) do nothing;

insert into public.spacing_constraints (congregation_id, constraint_kind, role_category, min_weeks, notes)
select c.id, 'same_role', null, 2, 'Padrão: 2 semanas entre a mesma categoria'
from public.congregations c where c.lgroup = 43741
on conflict do nothing;

insert into public.spacing_constraints (congregation_id, constraint_kind, role_category, min_weeks, notes)
select c.id, 'any_sister_fm', null, 3, 'Irmãs: mínimo 3 semanas entre qualquer parte Aplique-se (estudante/assistente)'
from public.congregations c where c.lgroup = 43741
on conflict do nothing;

-- RLS: desativado por padrão; use service_role no agente. Anon pode ser habilitado depois por tabela.
alter table public.members enable row level security;
alter table public.assignment_history enable row level security;
alter table public.meeting_programs enable row level security;
alter table public.rules_config enable row level security;
alter table public.spacing_constraints enable row level security;
alter table public.sync_runs enable row level security;
alter table public.draft_assignments enable row level security;

-- Política permissiva só para service_role (via bypass); anon sem políticas = bloqueado
comment on table public.members is 'Publicadores; sex usado para regra irmãs em FM 1–3';
