from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Job, JobEvent, JobStatus
from ..schemas import JobEventRead, JobRead


def add_status_event(db: Session, job: Job, status: JobStatus, note: str | None = None) -> JobEvent:
    job.status = status
    event = JobEvent(job=job, status=status, note=note)
    db.add(event)
    return event


def job_to_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        url=job.url,
        source=job.source,
        description=job.description,
        description_summary=job.description_summary,
        description_enriched_at=job.description_enriched_at,
        salary=job.salary,
        posted_date=job.posted_date,
        notes=job.notes,
        status=job.status,
        discovered_at=job.discovered_at,
        updated_at=job.updated_at,
        fit_score=job.fit_score,
        fit_verdict=job.fit_verdict,
        fit_summary=job.fit_summary,
        fit_strengths=job.get_fit_list("fit_strengths"),
        fit_gaps=job.get_fit_list("fit_gaps"),
        fit_method=job.fit_method,
        fit_message=job.fit_message,
        fit_analyzed_at=job.fit_analyzed_at,
        apply_mode=job.apply_mode,
        apply_confidence=job.apply_confidence,
        apply_prepared_at=job.apply_prepared_at,
        events=[JobEventRead.model_validate(event) for event in job.events],
    )


def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": job.source,
        "description": job.description,
        "salary": job.salary,
        "posted_date": job.posted_date,
        "status": job.status.value,
        "notes": job.notes,
        "discovered_at": job.discovered_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "events": [
            {
                "id": event.id,
                "status": event.status.value,
                "note": event.note,
                "created_at": event.created_at.isoformat(),
            }
            for event in job.events
        ],
    }
