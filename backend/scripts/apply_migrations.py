"""Apply backend/migrations/*.sql to the database in SUPABASE_DB_URL, once each.

    python -m scripts.apply_migrations --dry-run   # show what would run
    python -m scripts.apply_migrations             # apply pending migrations

Applied files are recorded in public.schema_migrations. If that table does not exist
yet but the app's tables do (a database set up by hand-running 001-004 as the README
used to describe), 001-004 are recorded as applied WITHOUT being re-run, then the rest
are applied. Each migration runs in its own transaction; the first failure stops the run."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

from app.core.config import settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
BASELINE_THROUGH = "004"


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))


async def main(dry_run: bool) -> int:
    conn = await asyncpg.connect(settings.SUPABASE_DB_URL, timeout=30)
    try:
        had_table = await conn.fetchval("select to_regclass('public.schema_migrations') is not null")
        have_app = await conn.fetchval("select to_regclass('public.documents') is not null")
        if not dry_run:
            await conn.execute(
                "create table if not exists public.schema_migrations "
                "(name text primary key, applied_at timestamptz not null default now())"
            )
        applied = (
            {r["name"] for r in await conn.fetch("select name from public.schema_migrations")}
            if had_table
            else set()
        )
        files = migration_files()
        if not had_table and have_app:
            baseline = [f.name for f in files if f.name[:3] <= BASELINE_THROUGH]
            print(f"existing database detected: recording {', '.join(baseline)} as already applied")
            if not dry_run:
                await conn.executemany(
                    "insert into public.schema_migrations(name) values($1) on conflict do nothing",
                    [(n,) for n in baseline],
                )
            applied |= set(baseline)
        pending = [f for f in files if f.name not in applied]
        if not pending:
            print("nothing to apply")
            return 0
        for f in pending:
            print(("would apply " if dry_run else "applying ") + f.name)
            if dry_run:
                continue
            async with conn.transaction():
                await conn.execute(f.read_text())
                await conn.execute("insert into public.schema_migrations(name) values($1)", f.name)
        print("done" if not dry_run else "dry run only; nothing changed")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().dry_run)))
