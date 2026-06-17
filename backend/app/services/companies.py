from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..database import engine
from ..models import TargetCompany
from .ats_parser import parse_careers_url
from .company_seeds import DEFAULT_TARGET_COMPANIES


def apply_parsed_company_fields(company: TargetCompany, careers_url: str) -> None:
    parsed = parse_careers_url(careers_url)
    company.careers_url = careers_url.strip()
    company.ats_type = parsed.ats_type
    company.board_token = parsed.board_token
    company.workday_host = parsed.workday_host


def ensure_target_company_schema() -> None:
    inspector = inspect(engine)
    if "target_companies" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("target_companies")}
    if "workday_host" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE target_companies ADD COLUMN workday_host VARCHAR(300)"))


def seed_default_companies(db: Session) -> int:
    existing_urls = {
        company.careers_url.strip().lower()
        for company in db.query(TargetCompany.careers_url).all()
    }
    added = 0

    for item in DEFAULT_TARGET_COMPANIES:
        careers_url = item["careers_url"].strip()
        if careers_url.lower() in existing_urls:
            continue

        parsed = parse_careers_url(careers_url)
        if parsed.ats_type == "unsupported":
            continue

        company = TargetCompany(name=item["name"].strip(), careers_url=careers_url)
        apply_parsed_company_fields(company, careers_url)
        db.add(company)
        existing_urls.add(careers_url.lower())
        added += 1

    if added:
        db.commit()
    return added
