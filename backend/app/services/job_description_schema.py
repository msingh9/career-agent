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
