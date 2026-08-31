# Copyright 2026 Manish Singh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Startup migration: add jobs.canonical_url, backfill it, and de-duplicate
existing rows that share a canonical URL (created before dedup was canonical)."""

from collections import defaultdict

from sqlalchemy import inspect, text

from ..database import SessionLocal, engine
from ..models import ApplyAttempt, Job, JobEvent
from .url_canonical import canonical_job_url

# Higher = keep this copy when de-duplicating (don't lose progress).
_STATUS_PRIORITY = {
    "offer": 6, "interview": 5, "applied": 4, "reviewing": 3,
    "withdrawn": 2, "passed": 1, "rejected": 1, "new": 0, "ignored": -1,
}


def ensure_job_dedup_schema() -> None:
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("jobs")}
    if "canonical_url" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN canonical_url VARCHAR(1000)"))

    db = SessionLocal()
    try:
        jobs = db.query(Job).all()

        # 1. Backfill canonical_url everywhere.
        for job in jobs:
            canon = canonical_job_url(job.url)
            if job.canonical_url != canon:
                job.canonical_url = canon
        db.commit()

        # 2. Collapse duplicates per (user, canonical_url).
        groups: dict[tuple, list[Job]] = defaultdict(list)
        for job in db.query(Job).all():
            groups[(job.user_id, job.canonical_url)].append(job)

        removed = 0
        for rows in groups.values():
            if len(rows) < 2:
                continue
            rows.sort(
                key=lambda r: (
                    _STATUS_PRIORITY.get(r.status.value, 0),
                    r.updated_at or r.discovered_at,
                ),
                reverse=True,
            )
            for extra in rows[1:]:
                db.query(ApplyAttempt).filter(ApplyAttempt.job_id == extra.id).delete(
                    synchronize_session=False
                )
                db.query(JobEvent).filter(JobEvent.job_id == extra.id).delete(
                    synchronize_session=False
                )
                db.delete(extra)
                removed += 1
        if removed:
            db.commit()
            print(f"[job_dedup] removed {removed} duplicate job(s)")
    finally:
        db.close()
