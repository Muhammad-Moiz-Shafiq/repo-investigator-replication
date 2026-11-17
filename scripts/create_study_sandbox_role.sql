-- Creates the read-only role for the scaled study's sandbox (option C,
-- docs/decisions.md 2026-10-24). It can read the 7 repository data tables,
-- with all their columns, and nothing else: not the 3 precomputed tables
-- left from the pilot (review_turnaround, daily_ci_failure_rate,
-- contributor_bugfix_association), whose definitions differ from the
-- questions and which no coverage level has. Unlike sandbox_readonly, it gets
-- no default privileges, so a table added later is not readable by accident.
-- The pilot's sandbox_readonly role is left as it was.
--
-- Run once with the admin connection. Not idempotent on purpose.
-- Usage: psql "$DATABASE_URL" -f scripts/create_study_sandbox_role.sql -v password="'<generated-password>'"

CREATE ROLE study_sandbox WITH LOGIN PASSWORD :password;
GRANT CONNECT ON DATABASE postgres TO study_sandbox;
GRANT USAGE ON SCHEMA public TO study_sandbox;
GRANT SELECT ON public.repos, public.commits, public.commit_files, public.pull_requests,
  public.pr_reviews, public.issues, public.ci_runs TO study_sandbox;
