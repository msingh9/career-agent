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

from sqlalchemy import inspect, text

from ..database import engine

JOB_DESCRIPTION_COLUMNS = (
    ("description_summary", "TEXT"),
    ("description_enriched_at", "DATETIME"),
)


def ensure_job_description_schema() -> None:
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        for name, column_type in JOB_DESCRIPTION_COLUMNS:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}"))
