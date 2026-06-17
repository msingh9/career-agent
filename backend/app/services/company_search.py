import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ..models import TargetCompany
from .ats_parser import workday_tenant_from_host
from .profile_match import job_matches_profile
from .search_agent import (
    job_matches_location_filter,
    should_exclude_job,
    upsert_job,
)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{token}?mode=json"
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_JOBS = 300
WORKDAY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSearchAgent/1.0)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip() or None


async def fetch_greenhouse_jobs(board_token: str) -> list[dict]:
    url = GREENHOUSE_API.format(token=board_token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    jobs: list[dict] = []
    for item in payload.get("jobs", []):
        location_obj = item.get("location") or {}
        jobs.append(
            {
                "title": item.get("title") or "Unknown title",
                "location": location_obj.get("name"),
                "url": item.get("absolute_url") or "",
                "description": _strip_html(item.get("content")),
                "posted_date": item.get("updated_at"),
                "source": "greenhouse",
            }
        )
    return [job for job in jobs if job["url"]]


async def fetch_lever_jobs(board_token: str) -> list[dict]:
    url = LEVER_API.format(token=board_token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    jobs: list[dict] = []
    for item in payload:
        categories = item.get("categories") or {}
        jobs.append(
            {
                "title": item.get("text") or "Unknown title",
                "location": categories.get("location"),
                "url": item.get("hostedUrl") or item.get("applyUrl") or "",
                "description": _strip_html(
                    f"{categories.get('team') or ''} {categories.get('commitment') or ''} {item.get('description') or ''}"
                ),
                "posted_date": item.get("createdAt"),
                "source": "lever",
            }
        )
    return [job for job in jobs if job["url"]]


async def fetch_workday_jobs(workday_host: str, board_token: str) -> list[dict]:
    tenant = workday_tenant_from_host(workday_host)
    if not tenant or not board_token:
        raise ValueError("Workday host or career site is missing.")

    api_url = f"https://{workday_host}/wday/cxs/{tenant}/{board_token}/jobs"
    jobs: list[dict] = []
    offset = 0

    async with httpx.AsyncClient(timeout=30.0, headers=WORKDAY_HEADERS) as client:
        while offset < WORKDAY_MAX_JOBS:
            response = await client.post(
                api_url,
                json={
                    "appliedFacets": {},
                    "limit": WORKDAY_PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            response.raise_for_status()
            payload = response.json()
            postings = payload.get("jobPostings") or []
            if not postings:
                break

            for item in postings:
                external_path = item.get("externalPath") or ""
                if not external_path:
                    continue
                jobs.append(
                    {
                        "title": item.get("title") or "Unknown title",
                        "location": item.get("locationsText"),
                        "url": f"https://{workday_host}/{board_token}{external_path}",
                        "description": item.get("locationsText"),
                        "posted_date": item.get("postedOn"),
                        "source": "workday",
                    }
                )

            offset += len(postings)
            total = payload.get("total")
            if total is not None and offset >= total:
                break
            if len(postings) < WORKDAY_PAGE_SIZE:
                break

    return jobs


async def fetch_company_jobs(company: TargetCompany) -> list[dict]:
    if company.ats_type == "greenhouse" and company.board_token:
        return await fetch_greenhouse_jobs(company.board_token)
    if company.ats_type == "lever" and company.board_token:
        return await fetch_lever_jobs(company.board_token)
    if company.ats_type == "workday" and company.board_token and company.workday_host:
        return await fetch_workday_jobs(company.workday_host, company.board_token)
    raise ValueError(f"{company.name} uses unsupported ATS ({company.ats_type}).")


def apply_company_to_jobs(jobs: list[dict], company_name: str) -> list[dict]:
    enriched: list[dict] = []
    for job in jobs:
        enriched.append({**job, "company": company_name})
    return enriched


async def run_company_search(
    db: Session,
    titles: list[str] | None = None,
    keywords: list[str] | None = None,
    locations: list[str] | None = None,
    skills: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    seniority: str | None = None,
) -> dict:
    companies = (
        db.query(TargetCompany)
        .filter(TargetCompany.enabled.is_(True))
        .order_by(TargetCompany.name.asc())
        .all()
    )
    if not companies:
        return {
            "found": 0,
            "added": 0,
            "skipped": 0,
            "companies_scanned": 0,
            "details": [],
            "message": "No enabled target companies. Add Greenhouse, Lever, or Workday career page URLs first.",
        }

    supported = [
        company
        for company in companies
        if company.ats_type in {"greenhouse", "lever", "workday"}
    ]
    if not supported:
        return {
            "found": 0,
            "added": 0,
            "skipped": 0,
            "companies_scanned": 0,
            "details": [],
            "message": (
                "No supported target companies. Use boards.greenhouse.io, "
                "jobs.lever.co, or myworkdayjobs.com URLs."
            ),
        }

    exclude_keywords = exclude_keywords or []
    total_found = 0
    total_added = 0
    total_skipped = 0
    details: list[dict] = []

    for company in supported:
        detail = {
            "company": company.name,
            "ats_type": company.ats_type,
            "found": 0,
            "added": 0,
            "skipped": 0,
            "filtered": 0,
            "error": None,
        }
        try:
            raw_jobs = await fetch_company_jobs(company)
            jobs = apply_company_to_jobs(raw_jobs, company.name)
            seen_urls: set[str] = set()

            for payload in jobs:
                url = payload.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                detail["found"] += 1

                if not job_matches_profile(payload, titles, keywords, skills, seniority):
                    detail["filtered"] += 1
                    continue
                if locations and not job_matches_location_filter(payload, locations):
                    detail["filtered"] += 1
                    continue
                if should_exclude_job(payload, exclude_keywords):
                    detail["filtered"] += 1
                    continue

                _, created = upsert_job(
                    db,
                    payload,
                    note=f"Discovered from {company.name} ({company.ats_type})",
                )
                if created:
                    detail["added"] += 1
                else:
                    detail["skipped"] += 1

            company.last_scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
            company.last_job_count = detail["found"]
        except Exception as exc:
            detail["error"] = str(exc)

        total_found += detail["found"]
        total_added += detail["added"]
        total_skipped += detail["skipped"]
        details.append(detail)

    db.commit()

    if total_added == 0 and not any(detail["error"] for detail in details):
        message = (
            f"Scanned {len(supported)} companies but no new matching jobs were added. "
            "Try broadening titles/keywords or location filters."
        )
    else:
        message = (
            f"Company search complete. Scanned {len(supported)} companies, "
            f"found {total_found}, added {total_added}, skipped {total_skipped} duplicates."
        )

    errors = [detail for detail in details if detail["error"]]
    if errors:
        message += f" {len(errors)} company request(s) failed."

    return {
        "found": total_found,
        "added": total_added,
        "skipped": total_skipped,
        "companies_scanned": len(supported),
        "details": details,
        "message": message,
    }
