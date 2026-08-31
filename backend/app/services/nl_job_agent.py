import json
import re

from openai import OpenAI
from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, JobEvent, JobStatus
from ..schemas_nl import (
    JobPreview,
    JobQueryFilters,
    JobQueryUpdate,
    NLJobPlan,
)
from .jobs import add_status_event

VALID_STATUSES = {status.value for status in JobStatus}
SENIOR_TITLE_TERMS = (
    "%vp%",
    "%vice president%",
    "%svp%",
    "%senior vice president%",
    "%director%",
    "%head of%",
    "%chief%",
    "%general manager%",
    "%executive%",
    "%president%",
)
NON_SENIOR_TITLE_TERMS = (
    "%intern%",
    "%junior%",
    "%associate%",
    "%coordinator%",
    "%analyst%",
    "%specialist%",
    "%assistant%",
    "%entry%",
)

SYSTEM_PROMPT = """You translate natural language requests about a personal job tracker into structured JSON.

Database tables:
- jobs(id, title, company, location, url, source, description, salary, posted_date, status, notes, discovered_at, updated_at)
- job_events(id, job_id, status, note, created_at)

Allowed actions:
- list: show matching jobs only
- delete: permanently remove matching jobs
- update: change fields on matching jobs
- ignore: set status to "ignored" (preferred when user says hide/ignore/dismiss)
- search: run a new job search. If the user describes what to look for (roles/titles, skills/keywords, locations), extract them into search_titles / search_keywords / search_locations. If they just say "search from my resume/profile", leave those empty to use saved criteria.
- company_search: search a specific company's careers page for roles (use when the user names a company to search, e.g. "search Nvidia", "find jobs at Stripe"). Put the company name in company_name. If the user includes a careers URL (greenhouse.io / lever.co / myworkdayjobs.com), put it in company_url.

Status values: new, reviewing, applied, rejected, interview, offer, withdrawn, passed, ignored

Senior executive roles typically include VP, SVP, Director, Senior Director, Head of, Chief, General Manager, President.
Non-senior roles include intern, junior, associate, coordinator, analyst, specialist, assistant, entry level.

Return JSON only:
{
  "action": "list|delete|update|ignore|search|company_search",
  "explanation": "plain English summary of what will happen",
  "company_name": null,
  "company_url": null,
  "search_titles": [],
  "search_keywords": [],
  "search_locations": [],
  "filters": {
    "company_contains": [],
    "company_excludes": [],
    "title_contains": [],
    "title_excludes": [],
    "location_contains": [],
    "source_in": [],
    "status_in": [],
    "status_not_in": [],
    "notes_contains": [],
    "senior_executive_only": false,
    "non_senior_only": false,
    "relevance_below": null,
    "relevance_at_least": null
  },
  "update": {
    "status": null,
    "notes_append": null
  }
}

Rules:
- Use company_contains for employer names when filtering EXISTING jobs (e.g. "ignore NVIDIA jobs" -> filters.company_contains ["nvidia"])
- Use company_search (not company_contains) when the user wants to FIND/SEARCH a company's new postings
- Use ignore action when user says ignore/hide/dismiss; use delete only for remove/delete
- For "not senior executive" set non_senior_only true and/or title_excludes with senior terms
- For "senior executive only" set senior_executive_only true
- For relevance/match/fit percentage to the profile: "below/less than/under N%" or "not more than N%" -> relevance_below = N; "at least/above/more than N%" -> relevance_at_least = N. These compare against the job's profile match score (0-100).
- Keep filter terms lowercase short strings
- update.status only for update/ignore actions
"""


def _like(term: str) -> str:
    return f"%{term.strip().lower()}%"


def _apply_filters(query, filters: JobQueryFilters):
    conditions = []

    for term in filters.company_contains:
        conditions.append(Job.company.ilike(_like(term)))
    for term in filters.company_excludes:
        conditions.append(not_(Job.company.ilike(_like(term))))

    for term in filters.title_contains:
        conditions.append(Job.title.ilike(_like(term)))
    for term in filters.title_excludes:
        conditions.append(not_(Job.title.ilike(_like(term))))

    for term in filters.location_contains:
        conditions.append(Job.location.ilike(_like(term)))

    for term in filters.notes_contains:
        conditions.append(Job.notes.ilike(_like(term)))

    if filters.source_in:
        conditions.append(or_(*[Job.source.ilike(_like(source)) for source in filters.source_in]))

    if filters.status_in:
        statuses = [status for status in filters.status_in if status in VALID_STATUSES]
        if statuses:
            conditions.append(Job.status.in_(statuses))

    if filters.status_not_in:
        statuses = [status for status in filters.status_not_in if status in VALID_STATUSES]
        if statuses:
            conditions.append(Job.status.notin_(statuses))

    if filters.senior_executive_only:
        conditions.append(or_(*[Job.title.ilike(term) for term in SENIOR_TITLE_TERMS]))

    if filters.non_senior_only:
        senior_match = or_(*[Job.title.ilike(term) for term in SENIOR_TITLE_TERMS])
        junior_match = or_(*[Job.title.ilike(term) for term in NON_SENIOR_TITLE_TERMS])
        conditions.append(not_(senior_match))
        conditions.append(junior_match)

    if conditions:
        query = query.filter(and_(*conditions))
    return query


def build_jobs_query(db: Session, filters: JobQueryFilters, user_id: int):
    return _apply_filters(db.query(Job).filter(Job.user_id == user_id), filters)


def build_sql_preview(filters: JobQueryFilters, action: str, update: JobQueryUpdate | None) -> str:
    clauses: list[str] = []

    for term in filters.company_contains:
        clauses.append(f"LOWER(company) LIKE '%{term.lower()}%'")
    for term in filters.company_excludes:
        clauses.append(f"LOWER(company) NOT LIKE '%{term.lower()}%'")
    for term in filters.title_contains:
        clauses.append(f"LOWER(title) LIKE '%{term.lower()}%'")
    for term in filters.title_excludes:
        clauses.append(f"LOWER(title) NOT LIKE '%{term.lower()}%'")
    for term in filters.location_contains:
        clauses.append(f"LOWER(location) LIKE '%{term.lower()}%'")
    for term in filters.notes_contains:
        clauses.append(f"LOWER(notes) LIKE '%{term.lower()}%'")
    if filters.source_in:
        values = ", ".join(f"'{value.lower()}'" for value in filters.source_in)
        clauses.append(f"LOWER(source) IN ({values})")
    if filters.status_in:
        values = ", ".join(f"'{value}'" for value in filters.status_in if value in VALID_STATUSES)
        if values:
            clauses.append(f"status IN ({values})")
    if filters.status_not_in:
        values = ", ".join(f"'{value}'" for value in filters.status_not_in if value in VALID_STATUSES)
        if values:
            clauses.append(f"status NOT IN ({values})")
    if filters.senior_executive_only:
        clauses.append("LOWER(title) LIKE '%vp%' OR LOWER(title) LIKE '%director%' OR LOWER(title) LIKE '%chief%' OR LOWER(title) LIKE '%head of%'")
    if filters.non_senior_only:
        clauses.append("(LOWER(title) NOT LIKE '%vp%' AND LOWER(title) NOT LIKE '%director%' AND LOWER(title) NOT LIKE '%chief%')")

    where_sql = " AND ".join(clauses) if clauses else "1=1"

    if action == "delete":
        return f"DELETE FROM jobs WHERE {where_sql};"
    if action in {"update", "ignore"}:
        status = (update.status if update else None) or "ignored"
        return f"UPDATE jobs SET status = '{status}' WHERE {where_sql};"
    return f"SELECT id, title, company, location, status, source FROM jobs WHERE {where_sql};"


def _heuristic_plan(query: str) -> dict:
    lower = query.lower()
    action = "list"

    url_match = re.search(r"https?://\S+", query)
    company_url = url_match.group(0) if url_match else None

    if any(word in lower for word in ("delete", "remove", "drop")):
        action = "delete"
    elif any(word in lower for word in ("ignore", "hide", "dismiss")):
        action = "ignore"
    elif any(word in lower for word in ("mark", "set", "update")):
        action = "update"
    elif any(word in lower for word in ("search", "find", "look for")):
        # "search jobs from my resume" vs "search company X"
        company_match = re.search(
            r"(?:search|find|look for)\s+(?:jobs?\s+(?:at|from|for)\s+)?([a-z0-9 .&-]+?)"
            r"(?:\s+careers?|\s+jobs?|\s+roles?|$)",
            lower,
        )
        if company_url or ("company" in lower) or (
            company_match and "resume" not in lower and "profile" not in lower
            and company_match.group(1).strip() not in {"jobs", "job", "roles", "new jobs"}
        ):
            action = "company_search"
        else:
            action = "search"

    company_name = None
    if action == "company_search":
        name_match = re.search(
            r"(?:company|at|for)\s+([a-z0-9 .&-]+?)(?:\s+careers?|\s+jobs?|\s+roles?|\s+https?|$)",
            lower,
        )
        if name_match:
            company_name = name_match.group(1).strip()

    filters: dict = {
        "company_contains": [],
        "company_excludes": [],
        "title_contains": [],
        "title_excludes": [],
        "location_contains": [],
        "source_in": [],
        "status_in": [],
        "status_not_in": [],
        "notes_contains": [],
        "senior_executive_only": False,
        "non_senior_only": False,
    }

    company_match = re.search(r"(?:from|at|for)\s+([a-z0-9 .&-]+?)(?:\s+jobs|\s+roles|$)", lower)
    if company_match:
        filters["company_contains"] = [company_match.group(1).strip()]

    if "senior executive" in lower or "executive only" in lower:
        filters["senior_executive_only"] = True
    if "not senior" in lower or "non senior" in lower or "not for senior" in lower:
        filters["non_senior_only"] = True

    update = {"status": None, "notes_append": None}
    if action == "ignore":
        update["status"] = "ignored"

    return {
        "action": action,
        "explanation": "Heuristic plan from your request. Add OPENAI_API_KEY for smarter parsing.",
        "company_name": company_name,
        "company_url": company_url,
        "filters": filters,
        "update": update,
    }


def generate_plan_from_query(query: str) -> dict:
    trimmed = query.strip()
    if not trimmed:
        raise ValueError("Enter a command describing what to do with your jobs.")

    if settings.openai_api_key:
        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": trimmed},
                ],
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception:
            pass

    return _heuristic_plan(trimmed)


def normalize_plan_data(
    data: dict,
) -> tuple[str, str, JobQueryFilters, JobQueryUpdate | None, str | None, str | None]:
    action = (data.get("action") or "list").strip().lower()
    if action not in {"list", "delete", "update", "ignore", "search", "company_search"}:
        action = "list"

    explanation = (data.get("explanation") or "Process matching jobs.").strip()
    filters = JobQueryFilters.model_validate(data.get("filters") or {})
    update_data = data.get("update") or {}
    update = JobQueryUpdate.model_validate(update_data) if update_data else None

    if action == "ignore":
        update = JobQueryUpdate(status="ignored", notes_append=update.notes_append if update else None)

    company_name = (data.get("company_name") or None)
    if isinstance(company_name, str):
        company_name = company_name.strip() or None
    company_url = (data.get("company_url") or None)
    if isinstance(company_url, str):
        company_url = company_url.strip() or None

    return action, explanation, filters, update, company_name, company_url


def _has_any_filter(f: JobQueryFilters) -> bool:
    return any([
        f.company_contains, f.company_excludes, f.title_contains, f.title_excludes,
        f.location_contains, f.source_in, f.status_in, f.status_not_in, f.notes_contains,
        f.senior_executive_only, f.non_senior_only,
        f.relevance_below is not None, f.relevance_at_least is not None,
    ])


def _relevance_filtered(jobs, filters: JobQueryFilters, db: Session, user_id: int):
    """Filter jobs by profile match score (relevance %) — computed, not a SQL column."""
    below, at_least = filters.relevance_below, filters.relevance_at_least
    if below is None and at_least is None:
        return jobs
    from .profile import get_or_create_profile
    from .profile_match import job_match_score

    p = get_or_create_profile(db, user_id)
    titles, keywords, skills = p.get_list("titles"), p.get_list("keywords"), p.get_list("skills")
    industries, exclude, sen = p.get_list("industries"), p.get_list("exclude_keywords"), p.seniority
    out = []
    for j in jobs:
        payload = {"title": j.title, "description": j.description or j.description_summary or ""}
        s = job_match_score(payload, titles, keywords, skills, industries, sen, exclude)
        if below is not None and s > below:
            continue
        if at_least is not None and s < at_least:
            continue
        out.append(j)
    return out


def create_plan(db: Session, query: str, user_id: int) -> NLJobPlan:
    raw = generate_plan_from_query(query)
    action, explanation, filters, update, company_name, company_url = normalize_plan_data(raw)

    # search / company_search do not filter existing jobs; skip the preview query.
    if action in {"search", "company_search"}:
        def _strlist(key):
            val = raw.get(key) or []
            return [str(v).strip() for v in val if str(v).strip()] if isinstance(val, list) else []

        return NLJobPlan(
            action=action,
            explanation=explanation,
            filters=filters,
            update=update,
            sql_preview="",
            requires_confirmation=False,
            affected_count=0,
            preview_jobs=[],
            company_name=company_name,
            company_url=company_url,
            search_titles=_strlist("search_titles"),
            search_keywords=_strlist("search_keywords"),
            search_locations=_strlist("search_locations"),
        )

    jobs = build_jobs_query(db, filters, user_id).order_by(Job.updated_at.desc()).all()
    jobs = _relevance_filtered(jobs, filters, db, user_id)
    preview_jobs = [
        JobPreview(
            id=job.id,
            title=job.title,
            company=job.company,
            location=job.location,
            status=job.status.value,
            source=job.source,
        )
        for job in jobs[:20]
    ]

    requires_confirmation = action in {"delete", "update", "ignore"}
    # Safety: a destructive action with no filter at all would hit every job.
    if requires_confirmation and not _has_any_filter(filters):
        explanation = "⚠ No filter was detected, so this matches ALL your jobs. " + explanation
    sql_preview = build_sql_preview(filters, action, update)

    return NLJobPlan(
        action=action,
        explanation=explanation,
        filters=filters,
        update=update,
        sql_preview=sql_preview,
        requires_confirmation=requires_confirmation,
        affected_count=len(jobs),
        preview_jobs=preview_jobs,
        company_name=company_name,
        company_url=company_url,
    )


def execute_plan(db: Session, plan: NLJobPlan, confirmed: bool, user_id: int) -> tuple[int, str]:
    if plan.requires_confirmation and not confirmed:
        raise ValueError("Confirmation is required before running this action.")

    jobs = build_jobs_query(db, plan.filters, user_id).all()
    jobs = _relevance_filtered(jobs, plan.filters, db, user_id)
    if not jobs:
        return 0, "No jobs matched your request."

    if plan.action == "list":
        return len(jobs), f"Found {len(jobs)} matching job(s)."

    if plan.action == "delete":
        job_ids = [job.id for job in jobs]
        db.query(JobEvent).filter(JobEvent.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.id.in_(job_ids)).delete(synchronize_session=False)
        db.commit()
        return len(job_ids), f"Deleted {len(job_ids)} job(s)."

    if plan.action in {"update", "ignore"}:
        update = plan.update or JobQueryUpdate(status="ignored")
        if update.status and update.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {update.status}")

        changed = 0
        for job in jobs:
            if update.status and job.status.value != update.status:
                add_status_event(
                    db,
                    job,
                    JobStatus(update.status),
                    note=plan.explanation[:200] or "Updated by job assistant",
                )
                changed += 1
            if update.notes_append:
                existing = job.notes or ""
                job.notes = f"{existing}\n{update.notes_append}".strip()
                changed += 1

        db.commit()
        verb = "Ignored" if plan.action == "ignore" else "Updated"
        return changed or len(jobs), f"{verb} {len(jobs)} job(s)."

    raise ValueError(f"Unsupported action: {plan.action}")
