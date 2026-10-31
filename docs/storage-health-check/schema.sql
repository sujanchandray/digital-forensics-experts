-- Run once in the Supabase SQL editor.
-- Put the project URL and the anon public key in docs/config.js.
-- Do not put the service role key in the site.

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null,
  role text not null check (role in ('client', 'professional')),
  expertise text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.profiles (id) on delete cascade,
  title text not null,
  category text not null check (category in (
    'Windows forensics',
    'Memory forensics',
    'Network forensics',
    'Mobile forensics',
    'E-mail forensics',
    'USB drive forensics',
    'Anti-forensics',
    'Linux forensics',
    'Cloud forensics',
    'Malware analysis',
    'Incident response',
    'Software testing'
  )),
  description text not null,
  created_at timestamptz not null default now()
);

create table public.proposals (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs (id) on delete cascade,
  professional_id uuid not null references public.profiles (id) on delete cascade,
  message text not null,
  created_at timestamptz not null default now(),
  unique (job_id, professional_id)
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs (id) on delete cascade,
  sender_id uuid not null references public.profiles (id) on delete cascade,
  body text not null,
  created_at timestamptz not null default now()
);

create index jobs_category_created_idx on public.jobs (category, created_at desc);
create index proposals_job_idx on public.proposals (job_id, created_at);
create index messages_job_created_idx on public.messages (job_id, created_at);

alter table public.profiles enable row level security;
alter table public.jobs enable row level security;
alter table public.proposals enable row level security;
alter table public.messages enable row level security;

create policy "profiles are public"
  on public.profiles for select
  using (true);

create policy "insert own profile"
  on public.profiles for insert
  with check (auth.uid() = id);

create policy "update own profile"
  on public.profiles for update
  using (auth.uid() = id);

create policy "jobs are public"
  on public.jobs for select
  using (true);

create policy "clients post own jobs"
  on public.jobs for insert
  with check (
    auth.uid() = client_id
    and exists (
      select 1 from public.profiles
      where id = auth.uid() and role = 'client'
    )
  );

create policy "participants read proposals"
  on public.proposals for select
  using (
    auth.uid() = professional_id
    or exists (
      select 1 from public.jobs
      where jobs.id = proposals.job_id and jobs.client_id = auth.uid()
    )
  );

create policy "professionals propose"
  on public.proposals for insert
  with check (
    auth.uid() = professional_id
    and exists (
      select 1 from public.profiles
      where id = auth.uid() and role = 'professional'
    )
    and exists (
      select 1 from public.jobs
      where jobs.id = proposals.job_id and jobs.client_id <> auth.uid()
    )
  );

create policy "participants read messages"
  on public.messages for select
  using (
    exists (
      select 1 from public.jobs
      where jobs.id = messages.job_id and jobs.client_id = auth.uid()
    )
    or exists (
      select 1 from public.proposals
      where proposals.job_id = messages.job_id
        and proposals.professional_id = auth.uid()
    )
  );

create policy "participants send messages"
  on public.messages for insert
  with check (
    auth.uid() = sender_id
    and (
      exists (
        select 1 from public.jobs
        where jobs.id = messages.job_id and jobs.client_id = auth.uid()
      )
      or exists (
        select 1 from public.proposals
        where proposals.job_id = messages.job_id
          and proposals.professional_id = auth.uid()
      )
    )
  );

grant usage on schema public to anon, authenticated;
grant select on public.profiles, public.jobs to anon, authenticated;
grant insert, update on public.profiles to authenticated;
grant insert on public.jobs, public.proposals, public.messages to authenticated;
grant select on public.proposals, public.messages to authenticated;

alter publication supabase_realtime add table public.jobs;
alter publication supabase_realtime add table public.messages;
