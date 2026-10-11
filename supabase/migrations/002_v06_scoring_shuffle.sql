-- Upgrade V0.5 -> V0.6
-- Aman dijalankan setelah 001_smaga_schema.sql pada project lama.

alter table public.exams
  add column if not exists shuffle_questions boolean not null default false,
  add column if not exists scoring_mode text not null default 'equal';

-- Tambahkan constraint hanya bila belum ada.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'exams_scoring_mode_check'
  ) then
    alter table public.exams
      add constraint exams_scoring_mode_check check (scoring_mode in ('equal','custom'));
  end if;
end $$;

alter table public.questions
  add column if not exists option_ids jsonb not null default '[]'::jsonb,
  add column if not exists shuffle_options boolean not null default false;

-- Migrasi ringan data lama: option_ids kosong akan dinormalisasi oleh server V0.6 saat ujian disimpan ulang.
