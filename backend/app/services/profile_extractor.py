import json
import re

from openai import OpenAI

from ..config import settings
from ..schemas import SearchProfileData
from .search_agent import pick_search_keywords, sanitize_extracted_profile

SEMICONDUCTOR_KEYWORDS = [
    "semiconductor",
    "semiconductors",
    "chip",
    "asic",
    "fpga",
    "soc",
    "fab",
    "foundry",
    "wafer",
    "eda",
    "gpu",
    "cpu",
    "analog",
    "rf",
    "cmos",
    "silicon",
    "photonics",
    "mems",
    "packaging",
    "yield",
    "vlsi",
    "dsp",
]

TITLE_NORMALIZE = {
    "vp": "VP",
    "svp": "SVP",
    "cto": "CTO",
    "ceo": "CEO",
    "cfo": "CFO",
    "coo": "COO",
}

SYSTEM_PROMPT = """You extract structured job search criteria from resumes.

Rules for job-board compatibility:
- titles must be SHORT role levels (1-3 words): "VP", "Senior Director", "Director"
- keywords must be SHORT search terms (1-2 words max): "ASIC", "SoC", "semiconductor", "VLSI"
- put longer phrases in skills, NOT keywords (e.g. "post-silicon debug" -> skills)
- industries can be 1-3 words: "semiconductors", "EDA", "automotive"
- exclude_keywords must be 1-2 words: "sales", "marketing"
- seniority is one short label: "VP", "Senior Director", "Director"

Return JSON only."""

EXTRACTION_PROMPT = """Analyze the resume and return JSON with these fields:

{
  "titles": ["VP", "Senior Director", "Director"],
  "keywords": ["semiconductor", "ASIC", "SoC", "VLSI"],
  "locations": ["California", "Remote"],
  "skills": ["Silicon Architecture", "Post-Silicon Debug", "Cross-Functional Leadership"],
  "industries": ["semiconductors", "automotive", "EDA"],
  "seniority": "VP",
  "exclude_keywords": ["sales", "marketing"],
  "summary": "2-3 sentences on search strategy"
}

Important:
- titles: 3-5 SHORT role levels only (never long titles like "VP of SoC Architecture and Delivery")
- keywords: 6-10 items, each 1-2 words, optimized for job board search
- skills: longer phrases allowed (5-10 items) — these are for your reference, not job board queries
- locations: cities, states, or "Remote"
- Focus on semiconductor/chip/hardware roles when the background supports it

Resume:
"""


def _normalize_title(value: str) -> str:
    cleaned = value.strip()
    key = cleaned.lower()
    if key in TITLE_NORMALIZE:
        return TITLE_NORMALIZE[key]
    return cleaned.title()


TITLE_PATTERNS = [
    r"\b(?:senior\s+)?vice\s+president\b",
    r"\bvp\b",
    r"\bsenior\s+director\b",
    r"\bdirector\b",
    r"\bhead\s+of\b",
    r"\bchief\b",
    r"\bcto\b",
    r"\bceo\b",
    r"\bgeneral\s+manager\b",
    r"\bprincipal\s+engineer\b",
    r"\bstaff\s+engineer\b",
    r"\bengineering\s+manager\b",
]

LOCATION_PATTERNS = [
    r"\b(?:san\s+)?jose\b",
    r"\bsanta\s+clara\b",
    r"\bsunnyvale\b",
    r"\bcupertino\b",
    r"\baustin\b",
    r"\bportland\b",
    r"\bseattle\b",
    r"\bboston\b",
    r"\bnew\s+york\b",
    r"\bcalifornia\b",
    r"\btexas\b",
    r"\bremote\b",
    r"\bbay\s+area\b",
]


def _normalize_list(values: list | None, limit: int | None = None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item).strip()
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


def _build_profile(
    titles: list[str],
    keywords: list[str],
    locations: list[str],
    skills: list[str],
    industries: list[str],
    seniority: str | None,
    exclude_keywords: list[str],
    summary: str | None,
) -> SearchProfileData:
    clean_titles, clean_keywords, clean_skills, clean_industries, clean_exclude = (
        sanitize_extracted_profile(
            titles,
            keywords,
            skills,
            industries,
            seniority,
            exclude_keywords,
        )
    )

    if not clean_titles:
        clean_titles = ["Director", "Senior Director", "VP"]
    if not clean_keywords:
        clean_keywords = pick_search_keywords([], clean_skills, clean_industries)

    return SearchProfileData(
        titles=clean_titles,
        keywords=clean_keywords,
        locations=_normalize_list(locations, 8),
        skills=clean_skills,
        industries=clean_industries,
        seniority=seniority,
        exclude_keywords=clean_exclude,
        summary=summary,
    )


def _heuristic_extract(resume_text: str) -> SearchProfileData:
    lower = resume_text.lower()

    keywords = [term for term in SEMICONDUCTOR_KEYWORDS if term in lower]
    if not keywords:
        keywords = ["semiconductor", "chip"]

    titles: list[str] = []
    for pattern in TITLE_PATTERNS:
        if re.search(pattern, lower):
            match = re.search(pattern, resume_text, re.IGNORECASE)
            if match:
                titles.append(_normalize_title(match.group(0)))
    if not titles:
        titles = ["Director", "Senior Director", "VP"]

    locations: list[str] = []
    for pattern in LOCATION_PATTERNS:
        if re.search(pattern, lower):
            match = re.search(pattern, resume_text, re.IGNORECASE)
            if match:
                locations.append(match.group(0).title())

    skills = keywords[:8]
    industries = ["semiconductors"]
    if "eda" in lower:
        industries.append("EDA")
    if "automotive" in lower:
        industries.append("automotive")

    seniority = "Senior Director"
    if re.search(r"\bvp\b|vice president", lower):
        seniority = "VP"
    elif re.search(r"\bdirector\b", lower):
        seniority = "Director"

    return _build_profile(
        titles=titles,
        keywords=keywords,
        locations=locations,
        skills=skills,
        industries=industries,
        seniority=seniority,
        exclude_keywords=[],
        summary=(
            "Heuristic profile from your resume. Configure OPENAI_API_KEY for richer AI extraction. "
            "Review and edit the criteria below before running a search."
        ),
    )


def extract_profile_from_resume(resume_text: str) -> tuple[SearchProfileData, str]:
    trimmed = resume_text[:12000]
    if settings.openai_api_key:
        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": EXTRACTION_PROMPT + trimmed},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            profile = _build_profile(
                titles=_normalize_list(data.get("titles"), 8),
                keywords=_normalize_list(data.get("keywords"), 15),
                locations=_normalize_list(data.get("locations"), 8),
                skills=_normalize_list(data.get("skills"), 12),
                industries=_normalize_list(data.get("industries"), 8),
                seniority=(data.get("seniority") or "").strip() or None,
                exclude_keywords=_normalize_list(data.get("exclude_keywords"), 8),
                summary=(data.get("summary") or "").strip() or None,
            )
            return profile, "openai"
        except Exception:
            pass

    return _heuristic_extract(trimmed), "heuristic"
