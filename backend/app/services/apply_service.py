import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import ApplyAttempt, Job, JobStatus
from ..schemas_apply import (
    ApplyAttemptRead,
    ApplyFeasibility,
    ApplyFillPayload,
    ApplyKit,
    ApplyStatusRead,
    AutoApplyResult,
    PrepareApplyResult,
)
from .apply_automation import run_apply_automation
from .apply_profile import read_apply_profile
from .apply_feasibility import assess_apply_feasibility
from .apply_fill_payload import build_fill_payload, career_agent_job_url, kit_from_job
from .apply_materials import build_apply_kit
from .jobs import add_status_event
from .profile import get_or_create_profile


def _kit_from_job(job: Job) -> ApplyKit | None:
    return kit_from_job(job)


def _store_apply_state(job: Job, feasibility: ApplyFeasibility, kit: ApplyKit) -> datetime:
    prepared_at = datetime.now(timezone.utc).replace(tzinfo=None)
    job.apply_mode = feasibility.apply_mode
    job.apply_confidence = feasibility.confidence
    job.apply_reasons = json.dumps(feasibility.reasons)
    job.apply_kit = kit.model_dump_json()
    job.apply_prepared_at = prepared_at
    return prepared_at


def get_apply_status(db: Session, job_id: int) -> ApplyStatusRead:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    profile = get_or_create_profile(db)
    feasibility = assess_apply_feasibility(job, profile)
    kit = _kit_from_job(job)

    latest = (
        db.query(ApplyAttempt)
        .filter(ApplyAttempt.job_id == job.id)
        .order_by(ApplyAttempt.created_at.desc())
        .first()
    )

    return ApplyStatusRead(
        job_id=job.id,
        feasibility=feasibility,
        kit=kit,
        prepared_at=job.apply_prepared_at,
        latest_attempt_status=latest.status if latest else None,  # type: ignore[arg-type]
    )


def prepare_apply(db: Session, job_id: int) -> PrepareApplyResult:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    profile = get_or_create_profile(db)
    feasibility = assess_apply_feasibility(job, profile)
    kit = build_apply_kit(job, profile)
    prepared_at = _store_apply_state(job, feasibility, kit)

    attempt = ApplyAttempt(
        job_id=job.id,
        mode=feasibility.apply_mode,
        status="prepared",
        confidence=feasibility.confidence,
        ats_type=feasibility.ats_type,
        message=feasibility.recommended_action,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    if feasibility.apply_mode == "manual_only":
        message = "Manual apply kit ready. Open the posting and use the prepared materials."
    elif feasibility.can_auto_submit:
        message = "Apply kit ready. Use browser assist fill or auto-apply if confidence checks pass."
    else:
        message = "Assisted apply kit ready. Use browser assist fill or copy materials manually."

    return PrepareApplyResult(
        job_id=job.id,
        feasibility=feasibility,
        kit=kit,
        prepared_at=prepared_at,
        attempt_id=attempt.id,
        message=message,
    )


def complete_apply(db: Session, job_id: int, note: str | None = None) -> Job:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    attempt = (
        db.query(ApplyAttempt)
        .filter(ApplyAttempt.job_id == job.id)
        .order_by(ApplyAttempt.created_at.desc())
        .first()
    )
    if attempt and attempt.status == "prepared":
        attempt.status = "completed"
        attempt.message = note or "Application submitted manually by user."

    add_status_event(
        db,
        job,
        JobStatus.APPLIED,
        note=note or "Marked applied after manual submission",
    )
    db.commit()
    db.refresh(job)
    return job


def list_apply_attempts(db: Session, job_id: int) -> list[ApplyAttemptRead]:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    attempts = (
        db.query(ApplyAttempt)
        .filter(ApplyAttempt.job_id == job.id)
        .order_by(ApplyAttempt.created_at.desc())
        .all()
    )
    return [ApplyAttemptRead.model_validate(item) for item in attempts]


def get_fill_payload(db: Session, job_id: int) -> ApplyFillPayload:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")
    profile = get_or_create_profile(db)
    return build_fill_payload(job, profile)


def get_assist_url(db: Session, job_id: int) -> dict:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")
    profile = get_or_create_profile(db)
    feasibility = assess_apply_feasibility(job, profile)
    if feasibility.ats_type not in {"greenhouse", "lever"}:
        raise ValueError("Browser assist fill is only available for Greenhouse and Lever postings.")

    attempt = ApplyAttempt(
        job_id=job.id,
        mode="assisted",
        status="manual_started",
        confidence=feasibility.confidence,
        ats_type=feasibility.ats_type,
        message="Browser assist fill started",
    )
    db.add(attempt)
    db.commit()

    return {
        "job_id": job.id,
        "url": career_agent_job_url(job.url, job.id),
        "message": "Opening posting for browser assist fill. Use the Career Agent extension to fill the form.",
    }


def run_auto_apply(
    db: Session,
    job_id: int,
    *,
    confirmed: bool,
    submit: bool,
) -> AutoApplyResult:
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise ValueError("Job not found.")

    if not confirmed:
        raise ValueError("Confirmation is required before auto-apply.")

    profile = get_or_create_profile(db)
    feasibility = assess_apply_feasibility(job, profile)
    apply_profile = read_apply_profile(profile)

    if feasibility.ats_type not in {"greenhouse", "lever"}:
        raise ValueError(f"Auto-apply is not supported for {feasibility.ats_type}.")

    if submit:
        if not feasibility.can_auto_submit:
            raise ValueError(
                "Auto-submit is not available for this job. Enable auto-apply in settings, "
                f"ensure confidence is at least {apply_profile.settings.min_auto_confidence}%, "
                "and use a Greenhouse or Lever posting."
            )
    elif not apply_profile.identity.email.strip():
        raise ValueError("Add your email in Apply profile before auto-fill.")

    if not _kit_from_job(job):
        prepare_apply(db, job_id)
        job = db.query(Job).filter(Job.id == job_id).one()

    result = run_apply_automation(job, profile, submit=submit, headless=True)

    attempt = ApplyAttempt(
        job_id=job.id,
        mode=feasibility.apply_mode,
        status=result.status if result.success else "failed",
        confidence=feasibility.confidence,
        ats_type=feasibility.ats_type,
        message=result.message,
    )
    db.add(attempt)

    if result.success and result.submitted:
        add_status_event(
            db,
            job,
            JobStatus.APPLIED,
            note="Auto-submitted via Career Agent",
        )
    elif result.success and result.status == "filled":
        add_status_event(
            db,
            job,
            JobStatus.REVIEWING,
            note="Auto-filled application form — review and submit",
        )

    db.commit()
    db.refresh(attempt)

    return AutoApplyResult(
        job_id=job.id,
        status=result.status,
        message=result.message,
        filled_fields=result.filled_fields,
        submitted=result.submitted,
        attempt_id=attempt.id,
        screenshot_path=result.screenshot_path,
    )
