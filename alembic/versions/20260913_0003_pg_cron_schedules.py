"""Supabase pg_cron schedules for the nightly refresh jobs.

Revision ID: 20260913_0003
Revises: 20260912_0002
Create Date: 2026-09-13

Matches SPEC §11 exactly: one cron entry per source, staggered 10 minutes apart
so no single job flirts with pg_cron's 10-min-per-job cap. The job body calls
the tracker API via `pg_net.http_post`, using an API key pulled from a Supabase
Vault setting (`app.tracker_api_key`) and a base URL setting
(`app.tracker_api_base_url`, e.g. https://tracker-api.example.com/api/v1).

Configure those settings in Supabase before running this migration:
  ALTER DATABASE postgres SET app.tracker_api_key = '…';
  ALTER DATABASE postgres SET app.tracker_api_base_url = 'https://…/api/v1';

The whole migration is guarded on the presence of `pg_cron` and `pg_net`, so it
no-ops cleanly on local Postgres (testcontainers) and on any environment where
those extensions aren't installed. Downgrade unschedules every entry it created.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260913_0003"
down_revision: str | None = "20260912_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (job_name, cron_expr, path)  — times are UTC; converted from PHT in SPEC §11.
_JOBS = [
    ("refresh-fx",                    "0 18 * * *",  "/jobs/refresh-fx"),
    ("refresh-prices-metagross",      "0 19 * * *",  "/jobs/refresh-prices/metagross"),
    ("refresh-prices-chrono24",       "10 19 * * *", "/jobs/refresh-prices/apify_chrono24"),
    ("refresh-prices-carousell-ph",   "20 19 * * *", "/jobs/refresh-prices/apify_carousell_ph"),
    ("refresh-prices-shopee-ph",      "30 19 * * *", "/jobs/refresh-prices/apify_shopee_ph"),
    ("refresh-prices-lamudi",         "40 19 * * *", "/jobs/refresh-prices/apify_lamudi"),
    ("refresh-prices-philkotse",      "50 19 * * *", "/jobs/refresh-prices/apify_philkotse"),
]


_GUARD = """
DO $$
DECLARE
  has_cron boolean;
  has_net  boolean;
BEGIN
  SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') INTO has_cron;
  SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_net')  INTO has_net;
  IF NOT (has_cron AND has_net) THEN
    RAISE NOTICE 'pg_cron/pg_net not installed; skipping cron schedule setup';
    RETURN;
  END IF;
{body}
END $$;
"""


def _schedule_sql() -> str:
    stmts = []
    for name, cron_expr, path in _JOBS:
        stmts.append(
            f"""
  PERFORM cron.schedule(
    '{name}',
    '{cron_expr}',
    $cmd$
      SELECT net.http_post(
        url     := current_setting('app.tracker_api_base_url') || '{path}',
        headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key'))
      );
    $cmd$
  );"""
        )
    return "\n".join(stmts)


def _unschedule_sql() -> str:
    stmts = []
    for name, _cron, _path in _JOBS:
        stmts.append(f"  PERFORM cron.unschedule('{name}');")
    return "\n".join(stmts)


def upgrade() -> None:
    op.execute(_GUARD.format(body=_schedule_sql()))


def downgrade() -> None:
    op.execute(_GUARD.format(body=_unschedule_sql()))
