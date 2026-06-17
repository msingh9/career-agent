from sqlalchemy import inspect, text

from ..database import engine

JOB_APPLY_COLUMNS = (
    ("apply_mode", "VARCHAR(30)"),
    ("apply_confidence", "INTEGER"),
    ("apply_reasons", "TEXT"),
    ("apply_kit", "TEXT"),
    ("apply_prepared_at", "DATETIME"),
)

PROFILE_APPLY_COLUMNS = (
    ("apply_identity", "TEXT"),
    ("apply_saved_answers", "TEXT"),
    ("apply_settings", "TEXT"),
)


def ensure_apply_schema() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "jobs" in table_names:
        columns = {column["name"] for column in inspector.get_columns("jobs")}
        with engine.begin() as conn:
            for name, column_type in JOB_APPLY_COLUMNS:
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}"))

    if "search_profiles" in table_names:
        columns = {column["name"] for column in inspector.get_columns("search_profiles")}
        with engine.begin() as conn:
            for name, column_type in PROFILE_APPLY_COLUMNS:
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE search_profiles ADD COLUMN {name} {column_type}"))

    if "apply_attempts" not in table_names:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apply_attempts (
                        id INTEGER PRIMARY KEY,
                        job_id INTEGER NOT NULL,
                        mode VARCHAR(30) NOT NULL,
                        status VARCHAR(30) NOT NULL,
                        confidence INTEGER NOT NULL,
                        ats_type VARCHAR(50) NOT NULL,
                        message TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        FOREIGN KEY(job_id) REFERENCES jobs(id)
                    )
                    """
                )
            )
