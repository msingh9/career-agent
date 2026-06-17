import re

from .search_agent import simplify_titles_for_search

EXECUTIVE_PATTERNS = [
    re.compile(r"\bvp\b", re.I),
    re.compile(r"vice\s+president", re.I),
    re.compile(r"\bsvp\b", re.I),
    re.compile(r"senior\s+vice\s+president", re.I),
    re.compile(r"senior\s+director", re.I),
    re.compile(r"\bdirector\b", re.I),
    re.compile(r"\bchief\b", re.I),
    re.compile(r"head\s+of", re.I),
    re.compile(r"general\s+manager", re.I),
    re.compile(r"\bcto\b", re.I),
    re.compile(r"\bceo\b", re.I),
    re.compile(r"\bpresident\b", re.I),
]

ENGINEER_WITHOUT_EXECUTIVE = re.compile(
    r"\bengineer\b",
    re.I,
)
EXECUTIVE_OVERRIDE = re.compile(
    r"director|vp|vice\s+president|svp|chief|head\s+of|general\s+manager|cto|ceo|president|principal",
    re.I,
)

CONFIGURED_TITLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "vp": re.compile(r"\bvp\b|vice\s+president|\bsvp\b|senior\s+vice\s+president", re.I),
    "senior director": re.compile(r"senior\s+director|sr\.?\s+director", re.I),
    "director": re.compile(r"\bdirector\b", re.I),
}


def _matches_configured_title(lower: str, profile_title: str) -> bool:
    term = profile_title.lower().strip()
    pattern = CONFIGURED_TITLE_PATTERNS.get(term)
    if pattern:
        return bool(pattern.search(lower))
    return term in lower


def is_executive_title(
    title: str,
    titles: list[str] | None,
    seniority: str | None,
) -> bool:
    text = (title or "").strip()
    if not text:
        return False

    lower = text.lower()

    for profile_title in simplify_titles_for_search(titles or [], seniority):
        if _matches_configured_title(lower, profile_title):
            return True

    if not any(pattern.search(lower) for pattern in EXECUTIVE_PATTERNS):
        return False

    if ENGINEER_WITHOUT_EXECUTIVE.search(lower) and not EXECUTIVE_OVERRIDE.search(lower):
        return False

    return True


def job_matches_profile(
    payload: dict,
    titles: list[str] | None,
    keywords: list[str] | None,
    skills: list[str] | None,
    seniority: str | None,
) -> bool:
    """Match company-board jobs against profile criteria.

    When titles or seniority are set, the job title must be executive level.
    Keywords/skills alone cannot bypass that requirement.
    """
    has_title_criteria = bool(titles or seniority)
    has_keyword_criteria = bool(keywords or skills)

    if not has_title_criteria and not has_keyword_criteria:
        return True

    job_title = payload.get("title") or ""

    if has_title_criteria and not is_executive_title(job_title, titles, seniority):
        return False

    if has_keyword_criteria and not has_title_criteria:
        haystack = f"{job_title} {payload.get('description') or ''}".lower()
        terms = [
            term.strip().lower()
            for term in (keywords or []) + (skills or [])
            if len(term.strip()) > 2
        ]
        return any(term in haystack for term in terms)

    return True
