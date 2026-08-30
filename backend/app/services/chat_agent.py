"""Unified chat brain: turns a chat message into a job-search action.

Reuses the existing natural-language planner (nl_job_agent) and the job/company
search services. Destructive actions (delete/update/ignore) come back with
requires_confirmation=True and the plan, so the frontend can confirm and then
call the existing /api/agent/nl-jobs/execute endpoint.
"""

from sqlalchemy.orm import Session

from ..models import Job, JobStatus, TargetCompany, User
from ..schemas_chat import ChatResponse
from .ats_parser import parse_careers_url
from .companies import apply_parsed_company_fields
from .company_search import run_company_search
from .jobs import job_to_read
from .nl_job_agent import create_plan
from .profile import get_or_create_profile
from .search_agent import run_job_search


def _recent_jobs(db: Session, user_id: int, limit: int = 25):
    rows = (
        db.query(Job)
        .filter(Job.user_id == user_id, Job.status != JobStatus.IGNORED)
        .order_by(Job.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [job_to_read(job) for job in rows]


def _profile_criteria(db: Session, user_id: int) -> dict:
    profile = get_or_create_profile(db, user_id)
    return {
        "titles": profile.get_list("titles"),
        "keywords": profile.get_list("keywords"),
        "locations": profile.get_list("locations"),
        "skills": profile.get_list("skills"),
        "industries": profile.get_list("industries"),
        "exclude_keywords": profile.get_list("exclude_keywords"),
        "seniority": profile.seniority,
    }


def _resolve_company(db: Session, user_id: int, name: str | None, url: str | None) -> TargetCompany | None:
    """Find (or create from a URL) the target company to search."""
    if url:
        clean = url.strip()
        existing = (
            db.query(TargetCompany)
            .filter(TargetCompany.user_id == user_id, TargetCompany.careers_url == clean)
            .one_or_none()
        )
        if existing:
            return existing
        parsed = parse_careers_url(clean)
        if parsed.ats_type == "unsupported":
            return None
        company = TargetCompany(
            name=(name or clean).strip(), careers_url=clean, user_id=user_id
        )
        apply_parsed_company_fields(company, clean)
        db.add(company)
        db.commit()
        db.refresh(company)
        return company

    if name:
        return (
            db.query(TargetCompany)
            .filter(
                TargetCompany.user_id == user_id,
                TargetCompany.name.ilike(f"%{name.strip()}%"),
            )
            .order_by(TargetCompany.name.asc())
            .first()
        )
    return None


async def run_chat(db: Session, user: User, message: str) -> ChatResponse:
    text = (message or "").strip()
    if not text:
        raise ValueError("Type a message describing what you'd like to do.")

    plan = create_plan(db, text, user.id)
    action = plan.action

    # --- Resume-based job search -------------------------------------------
    if action == "search":
        profile = get_or_create_profile(db, user.id)
        if not profile.resume_filename:
            return ChatResponse(
                reply=(
                    "Upload your resume first and I'll use it to search. "
                    "You can drop it in from the panel above the chat."
                ),
                action="search",
            )
        result = await run_job_search(db, user.id, **_profile_criteria(db, user.id))
        return ChatResponse(
            reply=result.get("message", "Search complete."),
            action="search",
            jobs=_recent_jobs(db, user.id),
        )

    # --- Company search -----------------------------------------------------
    if action == "company_search":
        company = _resolve_company(db, user.id, plan.company_name, plan.company_url)
        if not company:
            who = plan.company_name or "that company"
            return ChatResponse(
                reply=(
                    f"I couldn't find {who} in your target companies. Share its careers "
                    "URL (a boards.greenhouse.io, jobs.lever.co, or myworkdayjobs.com link) "
                    f'and I\'ll search it — e.g. "search {who} https://boards.greenhouse.io/{who}".'
                ),
                action="company_search",
            )
        criteria = _profile_criteria(db, user.id)
        criteria.pop("industries", None)  # run_company_search has no industries param
        result = await run_company_search(
            db, user.id, company_ids=[company.id], **criteria
        )
        return ChatResponse(
            reply=f"{company.name}: {result.get('message', 'Search complete.')}",
            action="company_search",
            jobs=_recent_jobs(db, user.id),
        )

    # --- Destructive actions need confirmation ------------------------------
    if plan.requires_confirmation:
        return ChatResponse(
            reply=plan.explanation
            + f" This affects {plan.affected_count} job(s). Confirm to proceed.",
            action=action,
            requires_confirmation=True,
            plan=plan,
        )

    # --- list / everything else -------------------------------------------
    matched = [
        job_to_read(job)
        for job in _matched_jobs(db, plan, user.id)
    ]
    reply = plan.explanation
    if action == "list":
        reply = f"Found {len(matched)} matching job(s)."
    return ChatResponse(reply=reply, action=action, jobs=matched)


def _matched_jobs(db: Session, plan, user_id: int):
    from .nl_job_agent import build_jobs_query

    return (
        build_jobs_query(db, plan.filters, user_id)
        .order_by(Job.updated_at.desc())
        .all()
    )
