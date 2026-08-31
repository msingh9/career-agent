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

import re

from .search_agent import should_exclude_job, simplify_titles_for_search

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


def strictness_to_threshold(strictness: int) -> int:
    """Map a 1–10 match-strictness dial to a 0–100 score threshold.

    1 (relaxed) ≈ 8 · 5 (default) ≈ 40 · 10 (only best matches) ≈ 80.
    """
    try:
        s = int(strictness)
    except (TypeError, ValueError):
        s = 5
    s = max(1, min(10, s))
    return s * 8


def job_match_score(
    payload: dict,
    titles: list[str] | None,
    keywords: list[str] | None,
    skills: list[str] | None,
    industries: list[str] | None,
    seniority: str | None,
    exclude_keywords: list[str] | None = None,
) -> int:
    """Graded 0–100 match of a job against resume-derived criteria.

    Title/seniority alignment contributes up to 45; keyword/skill/industry
    overlap up to 55 (each hit +12, capped). Excluded terms hard-fail to 0.
    """
    if exclude_keywords and should_exclude_job(payload, exclude_keywords):
        return 0

    title = payload.get("title") or ""
    haystack = f"{title} {payload.get('description') or ''}".lower()

    # Title/seniority alignment is the dominant signal (up to 55). A genuine
    # director+ title should clear the mid dial on its own; keyword overlap
    # (each hit +15, capped 45) pushes it into the strict range.
    title_score = 55 if is_executive_title(title, titles, seniority) else 0

    terms = {
        term.strip().lower()
        for term in (keywords or []) + (skills or []) + (industries or [])
        if len(term.strip()) > 2
    }
    matched = sum(1 for term in terms if term in haystack)
    keyword_score = min(45, matched * 15)

    return title_score + keyword_score
