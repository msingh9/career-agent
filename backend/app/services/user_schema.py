"""Startup migration for named multi-user profiles.

Adds a `users` table and a `user_id` column to jobs, search_profiles, and
target_companies, then backfills all pre-existing rows under a single
auto-created "Default" profile. Also rebuilds the `jobs` table to replace the
old global UNIQUE(url) constraint with a per-user UNIQUE(user_id, url), so two
profiles can independently track the same posting.

Mirrors the idempotent ``ensure_*_schema`` pattern used elsewhere
(see services/companies.py).
"""

import shutil

from sqlalchemy import inspect, text

from ..database import DATA_DIR, engine
from ..models import Job

DEFAULT_USER_NAME = "Default"


def _column_names(conn, table: str) -> list[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info('{table}')").fetchall()
    return [row[1] for row in rows]


def _has_global_unique_url(conn) -> bool:
    """True if a UNIQUE index covering exactly (url) exists on jobs."""
    for row in conn.exec_driver_sql("PRAGMA index_list('jobs')").fetchall():
        name, is_unique = row[1], row[2]
        if not is_unique:
            continue
        cols = [c[2] for c in conn.exec_driver_sql(f"PRAGMA index_info('{name}')").fetchall()]
        if cols == ["url"]:
            return True
    return False


def _rebuild_jobs_without_global_url_unique(conn) -> None:
    """Drop the legacy global UNIQUE(url) by rebuilding jobs from the model."""
    old_cols = _column_names(conn, "jobs")
    conn.exec_driver_sql("ALTER TABLE jobs RENAME TO jobs_old")
    # Recreate `jobs` from the current model (no global url unique; has user_id
    # and the composite UNIQUE(user_id, url) from __table_args__).
    Job.__table__.create(bind=conn)
    new_cols = _column_names(conn, "jobs")
    common = [c for c in new_cols if c in old_cols]
    collist = ", ".join(common)
    conn.exec_driver_sql(f"INSERT INTO jobs ({collist}) SELECT {collist} FROM jobs_old")
    conn.exec_driver_sql("DROP TABLE jobs_old")


def ensure_user_schema() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "jobs" not in tables:
        return  # brand-new DB: create_all already built the correct schema

    # Back up once before any structural change to the existing DB.
    needs_rebuild = False
    with engine.begin() as conn:
        needs_rebuild = _has_global_unique_url(conn)

    if needs_rebuild:
        db_file = DATA_DIR / "jobs.db"
        backup = DATA_DIR / "jobs.db.pre-multiuser.bak"
        if db_file.exists() and not backup.exists():
            shutil.copy2(db_file, backup)

    with engine.begin() as conn:
        # 1. Add user_id columns where missing.
        for table in ("jobs", "search_profiles", "target_companies"):
            if table in tables and "user_id" not in _column_names(conn, table):
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")

        # 1b. Add match_strictness (1–10) to search_profiles where missing.
        if "search_profiles" in tables and "match_strictness" not in _column_names(conn, "search_profiles"):
            conn.exec_driver_sql(
                "ALTER TABLE search_profiles ADD COLUMN match_strictness INTEGER DEFAULT 5 NOT NULL"
            )

        # 2. Replace legacy global UNIQUE(url) on jobs with per-user uniqueness.
        if needs_rebuild:
            _rebuild_jobs_without_global_url_unique(conn)

        # 3. Ensure at least one user exists (the Default profile).
        # `users` is created by Base.metadata.create_all before this runs.
        default_id = conn.exec_driver_sql(
            "SELECT id FROM users ORDER BY id LIMIT 1"
        ).scalar()
        if default_id is None:
            conn.exec_driver_sql(
                "INSERT INTO users (name) VALUES (:name)", {"name": DEFAULT_USER_NAME}
            )
            default_id = conn.exec_driver_sql(
                "SELECT id FROM users ORDER BY id LIMIT 1"
            ).scalar()

        # 4. Backfill any orphaned rows onto the default profile.
        for table in ("jobs", "search_profiles", "target_companies"):
            conn.exec_driver_sql(
                f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL",
                {"uid": default_id},
            )

        # 5. Enforce one profile per user going forward.
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_search_profiles_user "
            "ON search_profiles(user_id)"
        )
