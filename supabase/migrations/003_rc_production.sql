-- SMAGA Maliku Exam V1.0 RC1 — jalankan SETELAH 001 dan 002.
-- Periksa duplikasi exam_sessions participant_number dan submissions session_id
-- sebelum mengaktifkan indeks UNIQUE pada data lama.

create table if not exists public.staff_roles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('admin','teacher')),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.audit_logs (
  id bigint generated always as identity primary key,
  actor_id uuid references auth.users(id) on delete set null,
  action text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists audit_logs_created_at_idx on public.audit_logs(created_at desc);

alter table public.submissions add column if not exists payload_hash text;

-- Each participant gets at most one exam session; each session only one
-- official submission, even when two submit requests race.
create unique index if not exists sessions_one_participant_per_exam
  on public.exam_sessions(exam_id,participant_number);
create unique index if not exists submissions_one_per_session
  on public.submissions(session_id);

alter table public.staff_roles enable row level security;
alter table public.audit_logs enable row level security;
-- NO anon/authenticated policies: browser clients cannot read teacher roles/audit logs.
-- Production API exclusively uses service-role in a protected server environment.

-- IMPORTANT: Setelah akun guru dibuat via Supabase Auth > Users, grant secara manual:
-- insert into public.staff_roles (user_id, role)
-- select id, 'admin' from auth.users where email = 'GANTI_EMAIL_ADMIN';
