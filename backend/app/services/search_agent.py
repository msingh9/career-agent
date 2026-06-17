import asyncio
import re
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, JobStatus
from .jobs import add_status_event

MAX_QUERY_COMBOS = 18
FALLBACK_QUERIES = [
    "VP semiconductor",
    "Senior Director semiconductor",
    "Director ASIC",
    "VP engineering",
]

SENIORITY_PATTERNS = [
    (r"senior vice president|\bsvp\b", "SVP"),
    (r"vice president|\bvp\b", "VP"),
    (r"senior director", "Senior Director"),
    (r"\bdirector\b", "Director"),
    (r"\bcto\b|chief technology officer", "CTO"),
    (r"chief executive|\bceo\b", "CEO"),
    (r"general manager", "General Manager"),
]

SEARCHABLE_KEYWORDS = {
    "semiconductor",
    "semiconductors",
    "chip",
    "asic",
    "soc",
    "fpga",
    "vlsi",
    "gpu",
    "cpu",
    "eda",
    "fab",
    "foundry",
    "silicon",
    "analog",
    "rf",
    "cmos",
    "engineering",
    "hardware",
    "dsp",
    "ai",
}


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _dedupe(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if limit and len(result) >= limit:
            break
    return result


def default_search_params(
    titles: list[str] | None = None,
    keywords: list[str] | None = None,
    locations: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    return (
        titles or _parse_csv(settings.search_titles),
        keywords or _parse_csv(settings.search_keywords),
        locations or _parse_csv(settings.search_locations),
    )


def simplify_title_for_search(title: str) -> str:
    lower = title.lower()
    for pattern, label in SENIORITY_PATTERNS:
        if re.search(pattern, lower):
            return label

    words = [word for word in re.split(r"\s+", title.strip()) if word]
    if len(words) <= 3:
        return title.strip()
    return " ".join(words[:3])


def simplify_titles_for_search(titles: list[str], seniority: str | None = None) -> list[str]:
    simplified = [simplify_title_for_search(title) for title in titles]
    if seniority:
        seniority_text = seniority.strip()
        if seniority_text.lower() not in {title.lower() for title in simplified}:
            simplified.insert(0, seniority_text)
    return _dedupe(simplified, limit=6)


def _is_searchable_term(term: str) -> bool:
    words = term.split()
    lower = term.lower()
    if lower in SEARCHABLE_KEYWORDS:
        return True
    if len(words) > 2:
        return False
    if len(term) > 24:
        return False
    return True


def pick_search_keywords(
    keywords: list[str],
    skills: list[str] | None = None,
    industries: list[str] | None = None,
    limit: int = 5,
) -> list[str]:
    candidates: list[str] = []
    for term in keywords + (skills or []) + (industries or []):
        cleaned = term.strip()
        if not cleaned or not _is_searchable_term(cleaned):
            continue
        candidates.append(cleaned)

    prioritized: list[str] = []
    for term in candidates:
        if term.lower() in SEARCHABLE_KEYWORDS:
            prioritized.append(term)
    for term in candidates:
        if term not in prioritized:
            prioritized.append(term)

    if not prioritized:
        prioritized = ["semiconductor", "ASIC", "engineering"]

    return _dedupe(prioritized, limit=limit)


def _append_query(queries: list[str], seen: set[str], query: str) -> bool:
    text = query.strip()
    if not text or text in seen:
        return False
    seen.add(text)
    queries.append(text)
    return True


def build_search_queries(
    titles: list[str],
    keywords: list[str],
    skills: list[str] | None = None,
    industries: list[str] | None = None,
    seniority: str | None = None,
) -> list[str]:
    search_titles = simplify_titles_for_search(titles, seniority)
    search_keywords = pick_search_keywords(keywords, skills, industries)

    queries: list[str] = []
    seen: set[str] = set()

    # One title-only query per configured level so VP does not crowd out Director.
    for title in search_titles:
        if len(queries) >= MAX_QUERY_COMBOS:
            return queries
        _append_query(queries, seen, title)

    # Round-robin title + keyword combos so each title gets equal keyword coverage.
    if search_keywords:
        keyword_index = 0
        while len(queries) < MAX_QUERY_COMBOS:
            added_any = False
            for title in search_titles:
                if keyword_index >= len(search_keywords):
                    continue
                if _append_query(queries, seen, f"{title} {search_keywords[keyword_index]}"):
                    added_any = True
                if len(queries) >= MAX_QUERY_COMBOS:
                    return queries
            if not added_any:
                break
            keyword_index += 1

    for fallback in FALLBACK_QUERIES:
        if len(queries) >= MAX_QUERY_COMBOS:
            break
        _append_query(queries, seen, fallback)

    return queries or FALLBACK_QUERIES.copy()


REMOTE_TERMS = ("remote", "work from home", "wfh", "hybrid", "telecommute", "anywhere")

STATE_ABBREV_PATTERNS: dict[str, re.Pattern[str]] = {
    "california": re.compile(r"(?:,|\s)ca(?:,|\s|$)"),
    "texas": re.compile(r"(?:,|\s)tx(?:,|\s|$)"),
    "new york": re.compile(r"(?:,|\s)ny(?:,|\s|$)"),
    "washington": re.compile(r"(?:,|\s)wa(?:,|\s|$)"),
    "oregon": re.compile(r"(?:,|\s)or(?:,|\s|$)"),
    "arizona": re.compile(r"(?:,|\s)az(?:,|\s|$)"),
    "colorado": re.compile(r"(?:,|\s)co(?:,|\s|$)"),
    "florida": re.compile(r"(?:,|\s)fl(?:,|\s|$)"),
    "illinois": re.compile(r"(?:,|\s)il(?:,|\s|$)"),
    "massachusetts": re.compile(r"(?:,|\s)ma(?:,|\s|$)"),
}

LOCATION_EXPANSIONS: dict[str, list[str]] = {
    "california": [
        "san francisco",
        "san jose",
        "los angeles",
        "san diego",
        "santa clara",
        "sunnyvale",
        "cupertino",
        "palo alto",
        "mountain view",
        "fremont",
        "oakland",
        "sacramento",
        "irvine",
        "riverside",
        "temecula",
        "bay area",
        "silicon valley",
        "santa barbara",
        "pasadena",
        "berkeley",
        "menlo park",
        "redwood city",
        "san mateo",
        "pleasanton",
        "santa monica",
        "orange county",
        "riverside county",
    ],
}


def allows_remote(locations: list[str]) -> bool:
    return any(term.lower().strip() == "remote" for term in locations)


def is_remote_job(payload: dict) -> bool:
    location = (payload.get("location") or "").lower()
    return any(term in location for term in REMOTE_TERMS)


def _term_matches_location(job_location: str, term: str) -> bool:
    if not term:
        return False
    if term in job_location:
        return True
    for place in LOCATION_EXPANSIONS.get(term, []):
        if place in job_location:
            return True
    pattern = STATE_ABBREV_PATTERNS.get(term)
    if pattern:
        return bool(pattern.search(job_location))
    return False


def job_matches_location_filter(payload: dict, locations: list[str]) -> bool:
    if not locations:
        return True

    if is_remote_job(payload):
        return allows_remote(locations)

    job_location = (payload.get("location") or "").strip().lower()
    if not job_location or job_location in {"us", "usa", "united states"}:
        return False

    preferred = [term.lower().strip() for term in locations if term.strip() and term.lower().strip() != "remote"]
    if not preferred:
        return False

    return any(_term_matches_location(job_location, term) for term in preferred)


def should_exclude_job(payload: dict, exclude_keywords: list[str]) -> bool:
    if not exclude_keywords:
        return False
    haystack = " ".join(
        [
            payload.get("title") or "",
            payload.get("description") or "",
            payload.get("company") or "",
        ]
    ).lower()
    return any(term.lower() in haystack for term in exclude_keywords if term.strip())


async def fetch_adzuna_jobs(
    query: str,
    location: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return []

    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": min(max_results, 50),
        "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    country = settings.adzuna_country or "us"
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    results: list[dict] = []
    for item in payload.get("results", []):
        company = item.get("company", {}) or {}
        location_obj = item.get("location", {}) or {}
        results.append(
            {
                "title": item.get("title") or "Unknown title",
                "company": company.get("display_name") or "Unknown company",
                "location": location_obj.get("display_name"),
                "url": item.get("redirect_url") or item.get("url") or "",
                "source": "adzuna",
                "description": item.get("description"),
                "salary": _format_salary(item.get("salary_min"), item.get("salary_max")),
                "posted_date": item.get("created"),
            }
        )
    return [job for job in results if job["url"]]


def _format_salary(min_salary, max_salary) -> str | None:
    if min_salary and max_salary:
        return f"${int(min_salary):,} - ${int(max_salary):,}"
    if min_salary:
        return f"From ${int(min_salary):,}"
    if max_salary:
        return f"Up to ${int(max_salary):,}"
    return None


def upsert_job(
    db: Session,
    payload: dict,
    note: str = "Discovered by search agent",
) -> tuple[Job | None, bool]:
    url = payload.get("url", "").strip()
    if not url:
        return None, False

    existing = db.query(Job).filter(Job.url == url).one_or_none()
    if existing:
        return existing, False

    job = Job(
        title=payload.get("title") or "Unknown title",
        company=payload.get("company") or "Unknown company",
        location=payload.get("location"),
        url=url,
        source=payload.get("source") or "manual",
        description=payload.get("description"),
        salary=payload.get("salary"),
        posted_date=payload.get("posted_date"),
        status=JobStatus.NEW,
    )
    add_status_event(db, job, JobStatus.NEW, note=note)
    db.add(job)
    return job, True


async def _fetch_with_limit(
    semaphore: asyncio.Semaphore,
    query: str,
    location: str | None,
    max_results: int,
) -> list[dict] | Exception:
    async with semaphore:
        try:
            return await fetch_adzuna_jobs(query, location, max_results)
        except Exception as exc:
            return exc


async def _execute_search_batches(
    queries: list[str],
    per_query: int,
    use_location: str | None = None,
) -> tuple[list[dict], int]:
    semaphore = asyncio.Semaphore(4)
    tasks = [
        _fetch_with_limit(semaphore, query, use_location, per_query) for query in queries
    ]
    batches = await asyncio.gather(*tasks)

    payloads: list[dict] = []
    errors = 0
    for batch in batches:
        if isinstance(batch, Exception):
            errors += 1
            continue
        payloads.extend(batch)
    return payloads, errors


async def run_job_search(
    db: Session,
    titles: list[str] | None = None,
    keywords: list[str] | None = None,
    locations: list[str] | None = None,
    skills: list[str] | None = None,
    industries: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    seniority: str | None = None,
    max_results: int = 50,
) -> dict:
    titles, keywords, locations = default_search_params(titles, keywords, locations)
    queries = build_search_queries(titles, keywords, skills, industries, seniority)
    exclude_keywords = exclude_keywords or []
    from .profile_match import job_matches_profile

    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return {
            "found": 0,
            "added": 0,
            "skipped": 0,
            "message": (
                "Adzuna API keys are not configured. Copy .env.example to .env and add "
                "ADZUNA_APP_ID and ADZUNA_APP_KEY from https://developer.adzuna.com/. "
                "You can still add jobs manually in the UI."
            ),
        }

    per_query = max(5, max_results // max(len(queries), 1))
    payloads: list[dict] = []
    errors = 0

    if locations:
        search_places = [
            loc.strip()
            for loc in locations
            if loc.strip() and loc.strip().lower() != "remote"
        ]
        for place in search_places[:3]:
            batch, batch_errors = await _execute_search_batches(queries, per_query, place)
            payloads.extend(batch)
            errors += batch_errors
        if allows_remote(locations):
            batch, batch_errors = await _execute_search_batches(queries, per_query)
            payloads.extend(batch)
            errors += batch_errors
    else:
        payloads, errors = await _execute_search_batches(queries, per_query)

    if not payloads:
        fallback_location = None
        if locations:
            search_places = [
                loc.strip()
                for loc in locations
                if loc.strip() and loc.strip().lower() != "remote"
            ]
            fallback_location = search_places[0] if search_places else None
        payloads, fallback_errors = await _execute_search_batches(
            FALLBACK_QUERIES,
            max(8, per_query),
            fallback_location,
        )
        errors += fallback_errors

    found = 0
    added = 0
    skipped = 0
    excluded = 0
    profile_filtered = 0
    location_filtered = 0
    remote_filtered = 0
    seen_urls: set[str] = set()

    for payload in payloads:
        url = payload.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        found += 1
        if locations and is_remote_job(payload) and not allows_remote(locations):
            remote_filtered += 1
            continue
        if locations and not job_matches_location_filter(payload, locations):
            location_filtered += 1
            continue
        if should_exclude_job(payload, exclude_keywords):
            excluded += 1
            continue
        if not job_matches_profile(payload, titles, keywords, skills, seniority):
            profile_filtered += 1
            continue
        _, created = upsert_job(db, payload)
        if created:
            added += 1
        else:
            skipped += 1

    db.commit()

    if found == 0:
        message = (
            "No jobs found. Job boards work best with short terms like "
            "'VP semiconductor' or 'Director ASIC'."
        )
        if locations:
            message += f" Try broadening keywords or locations ({', '.join(locations)})."
        if errors:
            message += f" ({errors} API requests failed.)"
        return {"found": 0, "added": 0, "skipped": 0, "message": message}

    if added == 0 and found > 0 and locations:
        message = (
            f"Found {found} jobs from Adzuna, but none matched your location filter "
            f"({', '.join(locations)})."
        )
        if remote_filtered:
            message += f" {remote_filtered} remote listings were excluded."
        if location_filtered:
            message += f" {location_filtered} were outside your preferred locations."
        if errors:
            message += f" ({errors} API requests failed.)"
        return {"found": found, "added": 0, "skipped": 0, "message": message}

    message = f"Search complete. Found {found}, added {added}, skipped {skipped} duplicates."
    if location_filtered or remote_filtered:
        parts = []
        if location_filtered:
            parts.append(f"{location_filtered} outside your locations")
        if remote_filtered:
            parts.append(f"{remote_filtered} remote")
        message += f" Filtered out {', '.join(parts)}."
    if excluded:
        message += f" Excluded {excluded} by keyword filters."
    if profile_filtered:
        message += f" Skipped {profile_filtered} non-matching titles."
    if locations:
        message += f" Showing jobs matching: {', '.join(locations)}."
    if errors:
        message += f" ({errors} API requests failed.)"

    return {
        "found": found,
        "added": added,
        "skipped": skipped,
        "message": message,
    }


def _is_stored_keyword(term: str) -> bool:
    """Stricter than search-time filtering — profile keywords should be very short."""
    cleaned = term.strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower in SEARCHABLE_KEYWORDS:
        return True
    words = cleaned.split()
    if len(words) == 1:
        return 2 <= len(cleaned) <= 16
    if len(words) == 2:
        return all(2 <= len(word) <= 8 for word in words)
    return False


def sanitize_extracted_profile(
    titles: list[str],
    keywords: list[str],
    skills: list[str],
    industries: list[str],
    seniority: str | None,
    exclude_keywords: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """Normalize AI-extracted fields so stored criteria work on job boards."""
    clean_titles = simplify_titles_for_search(titles, seniority)

    clean_keywords = _dedupe([term for term in keywords if _is_stored_keyword(term)], limit=12)
    if len(clean_keywords) < 3:
        supplemental = pick_search_keywords(keywords, skills, industries, limit=10)
        clean_keywords = _dedupe(
            clean_keywords + [term for term in supplemental if _is_stored_keyword(term)],
            limit=12,
        )
    if not clean_keywords:
        clean_keywords = ["semiconductor", "ASIC", "engineering"]

    clean_skills = _dedupe(skills, limit=12)
    clean_industries = _dedupe(industries, limit=8)
    clean_exclude = _dedupe(
        [term for term in exclude_keywords if term.strip() and len(term.split()) <= 2],
        limit=8,
    )
    return clean_titles, clean_keywords, clean_skills, clean_industries, clean_exclude


def google_jobs_search_url(titles: list[str] | None = None, keywords: list[str] | None = None) -> str:
    titles, keywords, _ = default_search_params(titles, keywords, None)
    search_titles = simplify_titles_for_search(titles)
    search_keywords = pick_search_keywords(keywords)
    query = f"{search_titles[0]} {search_keywords[0]} jobs"
    return f"https://www.google.com/search?q={quote_plus(query)}&ibp=htl;jobs"
