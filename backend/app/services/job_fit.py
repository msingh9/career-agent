from datetime import datetime, timezone
from dataclasses import dataclass

import json
import re

from openai import OpenAI
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import RESUMES_DIR, engine
from ..models import Job, SearchProfile
from ..schemas import JobFitResult, SearchProfileData
from .profile import get_or_create_profile, profile_to_read
from .profile_match import is_executive_title
from .resume_parser import extract_text_from_resume

SYSTEM_PROMPT = """You assess how well a candidate fits a specific job posting.

The candidate is targeting senior semiconductor leadership roles (VP, Senior Director, Director).
Apply is always manual — provide guidance only, never instructions to auto-apply.

Return JSON only:
{
  "score": 0-100,
  "verdict": "Strong fit|Moderate fit|Weak fit|Poor fit",
  "summary": "2-3 sentences on overall fit",
  "strengths": ["3-6 specific alignment points"],
  "gaps": ["2-5 gaps, missing experience, or risks"]
}

Scoring guide:
- 80-100: Strong fit — title level aligns, core domain/skills match well
- 60-79: Moderate fit — worth pursuing with some gaps to address
- 40-59: Weak fit — notable mismatches in level, domain, or scope
- 0-39: Poor fit — major misalignment

Be direct and practical. Focus on semiconductor/chip/hardware leadership relevance."""

JD_SIGNAL_TERMS = [
    "semiconductor",
    "semiconductors",
    "asic",
    "soc",
    "fpga",
    "gpu",
    "cpu",
    "vlsi",
    "eda",
    "fab",
    "foundry",
    "silicon",
    "analog",
    "rf",
    "cmos",
    "photonics",
    "packaging",
    "yield",
    "npi",
    "tapeout",
    "post-silicon",
    "hardware",
    "engineering",
    "p&l",
    "operations",
    "leadership",
    "director",
    "vice president",
    "vp",
]

VERDICT_BANDS = (
    (80, "Strong fit"),
    (60, "Moderate fit"),
    (40, "Weak fit"),
    (0, "Poor fit"),
)

FIT_COLUMNS = (
    ("fit_score", "INTEGER"),
    ("fit_verdict", "VARCHAR(50)"),
    ("fit_summary", "TEXT"),
    ("fit_strengths", "TEXT"),
    ("fit_gaps", "TEXT"),
    ("fit_method", "VARCHAR(30)"),
    ("fit_message", "TEXT"),
    ("fit_analyzed_at", "DATETIME"),
)


@dataclass
class FitAnalysis:
    score: int
    verdict: str
    summary: str
    strengths: list[str]
    gaps: list[str]
    method: str
    message: str | None = None


def ensure_job_fit_schema() -> None:
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        for name, column_type in FIT_COLUMNS:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}"))


def _verdict_for_score(score: int) -> str:
    for threshold, label in VERDICT_BANDS:
        if score >= threshold:
            return label
    return "Poor fit"


def _dedupe_terms(values: list[str], limit: int | None = None) -> list[str]:
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


def load_stored_resume_text(profile: SearchProfile) -> str | None:
    if not profile.resume_filename:
        return None
    resume_path = RESUMES_DIR / profile.resume_filename
    if not resume_path.exists():
        return None
    try:
        return extract_text_from_resume(profile.resume_filename, resume_path.read_bytes())
    except Exception:
        return None


def _profile_context(profile: SearchProfile) -> SearchProfileData:
    return SearchProfileData(
        titles=profile.get_list("titles"),
        keywords=profile.get_list("keywords"),
        locations=profile.get_list("locations"),
        skills=profile.get_list("skills"),
        industries=profile.get_list("industries"),
        seniority=profile.seniority,
        exclude_keywords=profile.get_list("exclude_keywords"),
        summary=profile.summary,
    )


def _candidate_terms(profile: SearchProfileData, resume_text: str | None) -> list[str]:
    terms = (
        profile.titles
        + profile.keywords
        + profile.skills
        + profile.industries
        + ([profile.seniority] if profile.seniority else [])
    )
    if profile.summary:
        terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9&/+.-]{2,}", profile.summary))
    if resume_text:
        terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9&/+.-]{2,}", resume_text[:6000]))
    return _dedupe_terms(terms, limit=80)


def _term_in_text(term: str, text: str) -> bool:
    cleaned = term.strip().lower()
    if not cleaned or len(cleaned) < 2:
        return False
    if " " in cleaned or len(cleaned) > 20:
        return cleaned in text
    return bool(re.search(rf"\b{re.escape(cleaned)}\b", text))


def _heuristic_fit(
    job: Job,
    profile: SearchProfileData,
    resume_text: str | None,
) -> FitAnalysis:
    job_text = " ".join(
        part for part in [job.title, job.company, job.location or "", job.description or ""] if part
    ).lower()
    candidate_text = " ".join(
        part
        for part in [
            profile.summary or "",
            resume_text or "",
            ", ".join(profile.skills),
            ", ".join(profile.keywords),
            ", ".join(profile.titles),
            profile.seniority or "",
        ]
        if part
    ).lower()

    profile_terms = _candidate_terms(profile, resume_text)
    strengths: list[str] = []
    for term in profile_terms:
        if _term_in_text(term, job_text):
            label = term if len(term) <= 40 else term[:37] + "..."
            if label.lower() not in {item.lower() for item in strengths}:
                strengths.append(f"Profile/resume highlights {label}, which the role mentions.")
            if len(strengths) >= 6:
                break

    if is_executive_title(job.title, profile.titles, profile.seniority):
        strengths.insert(0, f"Title level aligns with your target roles ({', '.join(profile.titles[:3])}).")

    gaps: list[str] = []
    for signal in JD_SIGNAL_TERMS:
        if _term_in_text(signal, job_text) and not _term_in_text(signal, candidate_text):
            gaps.append(f"Role emphasizes {signal}; limited evidence in your profile/resume.")
        if len(gaps) >= 5:
            break

    if not resume_text and not profile.summary:
        gaps.append("Upload a resume or add a profile summary for richer fit analysis.")

    if job.description and len(job.description.strip()) < 80:
        gaps.append("Job description is short — open the posting for full requirements before applying.")

    overlap_ratio = len(strengths) / max(len(profile_terms[:20]), 1)
    title_bonus = 25 if is_executive_title(job.title, profile.titles, profile.seniority) else 0
    score = min(100, int(35 + overlap_ratio * 35 + title_bonus - len(gaps) * 4))
    score = max(0, score)

    if score >= 80:
        summary = "Strong alignment between your background and this role. Worth prioritizing if the scope interests you."
    elif score >= 60:
        summary = "Reasonable fit with some gaps to address in outreach or interviews. Review the posting before investing time."
    elif score >= 40:
        summary = "Mixed fit — relevant elements exist but notable gaps or level/scope questions remain."
    else:
        summary = "Limited alignment with your profile. Consider whether the role level or domain matches your goals."

    return FitAnalysis(
        score=score,
        verdict=_verdict_for_score(score),
        summary=summary,
        strengths=strengths[:6] or ["No strong keyword overlaps detected — review the posting manually."],
        gaps=gaps[:5] or ["No major gaps flagged by keyword analysis."],
        method="heuristic",
        message="Heuristic analysis from profile and resume keywords. Add OPENAI_API_KEY for deeper assessment.",
    )


def _build_fit_prompt(job: Job, profile: SearchProfileData, resume_text: str | None) -> str:
    resume_section = (resume_text or "")[:10000]
    if not resume_section:
        resume_section = "(No resume on file — use profile fields only.)"

    return f"""Job posting:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or "Not listed"}
- Salary: {job.salary or "Not listed"}
- Description:
{(job.description or "No description stored. Use title and company context only.")[:8000]}

Candidate profile:
- Target titles: {", ".join(profile.titles) or "Not set"}
- Seniority: {profile.seniority or "Not set"}
- Keywords: {", ".join(profile.keywords) or "Not set"}
- Skills: {", ".join(profile.skills) or "Not set"}
- Industries: {", ".join(profile.industries) or "Not set"}
- Strategy summary: {profile.summary or "Not set"}

Resume excerpt:
{resume_section}
"""


def _openai_fit(
    job: Job,
    profile: SearchProfileData,
    resume_text: str | None,
) -> FitAnalysis:
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_fit_prompt(job, profile, resume_text)},
        ],
    )
    data = json.loads(response.choices[0].message.content or "{}")
    score = max(0, min(100, int(data.get("score", 0))))
    strengths = [str(item).strip() for item in data.get("strengths", []) if str(item).strip()][:6]
    gaps = [str(item).strip() for item in data.get("gaps", []) if str(item).strip()][:5]
    return FitAnalysis(
        score=score,
        verdict=(data.get("verdict") or _verdict_for_score(score)).strip(),
        summary=(data.get("summary") or "Fit analysis complete.").strip(),
        strengths=strengths or ["No specific strengths identified."],
        gaps=gaps or ["No specific gaps identified."],
        method="openai",
        message="AI fit analysis based on your resume and profile. Apply manually on the company site.",
    )


def _save_fit_analysis(db: Session, job: Job, analysis: FitAnalysis) -> JobFitResult:
    analyzed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    job.fit_score = analysis.score
    job.fit_verdict = analysis.verdict
    job.fit_summary = analysis.summary
    job.set_fit_list("fit_strengths", analysis.strengths)
    job.set_fit_list("fit_gaps", analysis.gaps)
    job.fit_method = analysis.method
    job.fit_message = analysis.message
    job.fit_analyzed_at = analyzed_at
    db.commit()
    db.refresh(job)
    return JobFitResult(
        job_id=job.id,
        score=analysis.score,
        verdict=analysis.verdict,
        summary=analysis.summary,
        strengths=analysis.strengths,
        gaps=analysis.gaps,
        method=analysis.method,
        message=analysis.message,
        analyzed_at=analyzed_at,
    )


def analyze_job_fit(db: Session, job_id: int) -> JobFitResult:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    profile_row = get_or_create_profile(db)
    profile = _profile_context(profile_row)
    resume_text = load_stored_resume_text(profile_row)

    if settings.openai_api_key:
        try:
            return _save_fit_analysis(db, job, _openai_fit(job, profile, resume_text))
        except Exception:
            pass

    analysis = _heuristic_fit(job, profile, resume_text)
    if profile_to_read(profile_row).has_openai:
        analysis.message = "AI fit analysis failed; showing keyword-based estimate instead."
    return _save_fit_analysis(db, job, analysis)
