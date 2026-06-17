import json
from urllib.parse import urlparse

from ..database import RESUMES_DIR
from ..models import Job, SearchProfile
from ..schemas_apply import ApplyFillAnswer, ApplyFillPayload, ApplyKit
from .apply_feasibility import assess_apply_feasibility, _detect_ats_from_url
from .apply_profile import read_apply_profile


def kit_from_job(job: Job) -> ApplyKit | None:
    if not job.apply_kit:
        return None
    try:
        import json

        return ApplyKit.model_validate(json.loads(job.apply_kit))
    except (json.JSONDecodeError, ValueError):
        return None


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path}".lower()


def find_job_by_url(db_session, url: str) -> Job | None:
    from ..models import Job

    target = _normalize_url(url)
    jobs = db_session.query(Job).all()
    for job in jobs:
        if _normalize_url(job.url) == target:
            return job
        if target in _normalize_url(job.url) or _normalize_url(job.url) in target:
            return job
    return None


def build_fill_payload(job: Job, profile: SearchProfile, kit: ApplyKit | None = None) -> ApplyFillPayload:
    apply_profile = read_apply_profile(profile)
    identity = apply_profile.identity
    kit = kit or kit_from_job(job)
    materials = kit.materials if kit else None

    first_name, last_name = _split_name(identity.full_name)
    ats_type, _ = _detect_ats_from_url(job.url)
    feasibility = assess_apply_feasibility(job, profile)

    answers: list[ApplyFillAnswer] = []
    if materials:
        answers = [
            ApplyFillAnswer(question=item.question, answer=item.answer) for item in materials.answers
        ]
        if materials.why_this_role:
            answers.append(ApplyFillAnswer(question="why interested", answer=materials.why_this_role))

    for saved in apply_profile.saved_answers:
        if saved.answer.strip():
            answers.append(ApplyFillAnswer(question=saved.label.lower(), answer=saved.answer))

    resume_filename = profile.resume_filename
    resume_path = RESUMES_DIR / resume_filename if resume_filename else None
    resume_available = bool(resume_path and resume_path.exists())

    return ApplyFillPayload(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        job_url=job.url,
        ats_type=ats_type,
        apply_mode=feasibility.apply_mode,
        confidence=feasibility.confidence,
        can_auto_submit=feasibility.can_auto_submit,
        fields={
            "first_name": first_name,
            "last_name": last_name,
            "full_name": identity.full_name,
            "email": identity.email,
            "phone": identity.phone,
            "linkedin_url": identity.linkedin_url,
            "website": identity.website,
            "location": identity.location or job.location or "",
            "work_authorization": identity.work_authorization,
            "requires_sponsorship": "Yes" if identity.requires_sponsorship else "No",
            "cover_letter": materials.cover_letter if materials else "",
            "outreach_email": materials.outreach_email if materials else "",
        },
        answers=answers,
        resume_available=resume_available,
        resume_filename=resume_filename,
    )


def career_agent_job_url(job_url: str, job_id: int) -> str:
    separator = "&" if "?" in job_url else "?"
    return f"{job_url}{separator}career_agent_job={job_id}"
