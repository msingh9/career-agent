import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job
from ..schemas import JobDescriptionEnrichResult

MIN_USEFUL_DESCRIPTION = 280
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSearchAgent/1.0)",
    "Accept": "text/html,application/json",
}

SYSTEM_PROMPT = """You summarize job postings for senior job seekers.

Return JSON only:
{
  "summary": "3-5 concise sentences covering role scope, team, and key requirements",
  "highlights": ["4-6 short bullet points: responsibilities, must-haves, location/level notes"]
}

Rules:
- Be factual — only use information from the posting text
- Mention seniority level, domain (e.g. semiconductors), and location if present
- Do not invent benefits, compensation, or requirements not in the text
- If the posting text is very short, say what is known and note that details may be on the company site
"""


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def _parse_greenhouse_job_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "greenhouse.io" not in host:
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if "jobs" not in parts:
        return None
    job_index = parts.index("jobs")
    if job_index < 1 or job_index + 1 >= len(parts):
        return None
    board = parts[job_index - 1]
    job_id = parts[job_index + 1]
    if not job_id.isdigit():
        return None
    return board, job_id


def _parse_lever_job_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if "jobs.lever.co" not in parsed.netloc.lower():
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


async def _fetch_greenhouse_description(url: str) -> str | None:
    parsed = _parse_greenhouse_job_url(url)
    if not parsed:
        return None
    board, job_id = parsed
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(api_url)
        response.raise_for_status()
        payload = response.json()
    return _strip_html(payload.get("content")) or None


async def _fetch_lever_description(url: str) -> str | None:
    parsed = _parse_lever_job_url(url)
    if not parsed:
        return None
    company, posting_id = parsed
    api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(api_url)
        response.raise_for_status()
        payload = response.json()
    categories = payload.get("categories") or {}
    parts = [
        categories.get("team") or "",
        categories.get("commitment") or "",
        categories.get("location") or "",
        _strip_html(payload.get("description")),
    ]
    text = " ".join(part for part in parts if part).strip()
    return text or None


async def _fetch_html_description(url: str) -> str | None:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=FETCH_HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        match = re.search(pattern, html, re.I)
        if match:
            text = _strip_html(match.group(1))
            if len(text) >= 80:
                return text

    for pattern in (
        r'<div[^>]+class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>',
        r"<main[^>]*>(.*?)</main>",
        r"<article[^>]*>(.*?)</article>",
    ):
        match = re.search(pattern, html, re.I | re.S)
        if match:
            text = _strip_html(match.group(1))
            if len(text) >= 120:
                return text[:12000]

    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.I | re.S)
    if body_match:
        text = _strip_html(body_match.group(1))
        if len(text) >= 120:
            return text[:8000]
    return None


async def fetch_full_description(job: Job) -> tuple[str | None, str]:
    existing = (job.description or "").strip()
    if len(existing) >= MIN_USEFUL_DESCRIPTION:
        return existing, "stored"

    for fetcher, source in (
        (_fetch_greenhouse_description, "greenhouse"),
        (_fetch_lever_description, "lever"),
        (_fetch_html_description, "html"),
    ):
        try:
            text = await fetcher(job.url)
            if text and len(text.strip()) >= 80:
                return text.strip(), source
        except Exception:
            continue

    if existing:
        return existing, "stored_partial"
    return None, "unavailable"


def _heuristic_summary(job: Job, description: str) -> str:
    text = description.strip()
    if not text:
        return (
            f"{job.title} at {job.company}"
            + (f" ({job.location})" if job.location else "")
            + ". Full description not available — open the posting for details."
        )

    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentences[:3]).strip()
    if len(summary) > 500:
        summary = summary[:497] + "..."

    lines = [f"{job.title} at {job.company}"]
    if job.location:
        lines.append(f"Location: {job.location}")
    lines.append(summary)

    keywords = ("director", "vp", "vice president", "semiconductor", "asic", "engineering", "lead")
    found = [word for word in keywords if word in text.lower()]
    if found:
        lines.append("Themes: " + ", ".join(dict.fromkeys(found)))

    return "\n\n".join(lines)


def _openai_summary(job: Job, description: str) -> tuple[str, str]:
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Title: {job.title}\nCompany: {job.company}\n"
                    f"Location: {job.location or 'Not listed'}\n\nPosting:\n{description[:10000]}"
                ),
            },
        ],
    )
    data = json.loads(response.choices[0].message.content or "{}")
    summary = str(data.get("summary", "")).strip()
    highlights = [str(item).strip() for item in data.get("highlights", []) if str(item).strip()]
    parts = [summary] if summary else []
    if highlights:
        parts.append("\n".join(f"• {item}" for item in highlights[:6]))
    return "\n\n".join(parts).strip(), "openai"


def summarize_description(job: Job, description: str) -> tuple[str, str]:
    text = description.strip()
    if not text:
        return _heuristic_summary(job, ""), "heuristic"

    if settings.openai_api_key and len(text) >= 80:
        try:
            return _openai_summary(job, text)
        except Exception:
            pass

    return _heuristic_summary(job, text), "heuristic"


async def enrich_job_description(db: Session, job_id: int) -> JobDescriptionEnrichResult:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    description, fetch_source = await fetch_full_description(job)
    if description and len(description) > len(job.description or ""):
        job.description = description

    summary, summary_method = summarize_description(job, description or job.description or "")
    enriched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    job.description_summary = summary
    job.description_enriched_at = enriched_at
    db.commit()
    db.refresh(job)

    if fetch_source == "unavailable" and not description:
        message = "Could not fetch a full posting. Summary is based on title and company only."
    elif summary_method == "openai":
        message = "Job description fetched and summarized."
    else:
        message = "Job description summarized."

    return JobDescriptionEnrichResult(
        job_id=job.id,
        description=job.description,
        description_summary=summary,
        description_enriched_at=enriched_at,
        fetch_source=fetch_source,
        summary_method=summary_method,
        message=message,
    )
