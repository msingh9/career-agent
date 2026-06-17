from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from .database import RESUMES_DIR, get_db
from .models import ApplyAttempt, Job, JobEvent, JobStatus, TargetCompany
from .schemas import (
    CompanySearchResult,
    DashboardStats,
    JobCreate,
    JobDescriptionEnrichResult,
    JobFitResult,
    JobRead,
    JobUpdate,
    ResumeUploadResult,
    SearchProfileRead,
    SearchProfileUpdate,
    SearchRequest,
    SearchResult,
    StatusUpdate,
    TargetCompanyCreate,
    TargetCompanyRead,
    TargetCompanyUpdate,
)
from .schemas_apply import (
    ApplyAttemptRead,
    ApplyProfileExtractResult,
    ApplyProfileRead,
    ApplyProfileUpdate,
    ApplyFillPayload,
    ApplyStatusRead,
    AutoApplyRequest,
    AutoApplyResult,
    CompleteApplyRequest,
    PrepareApplyResult,
)
from .services.apply_profile import (
    populate_apply_profile_from_resume,
    read_apply_profile,
    update_apply_profile,
)
from .services.apply_service import (
    complete_apply,
    get_apply_status,
    get_assist_url,
    get_fill_payload,
    list_apply_attempts,
    prepare_apply,
    run_auto_apply,
)
from .services.apply_automation import SCREENSHOTS_DIR
from .services.apply_fill_payload import find_job_by_url
from .services.companies import apply_parsed_company_fields
from .services.ats_parser import parse_careers_url
from .services.company_search import run_company_search
from .services.jobs import add_status_event, job_to_read
from .services.job_fit import analyze_job_fit
from .services.job_description import enrich_job_description
from .services.profile import (
    apply_profile_data,
    get_or_create_profile,
    profile_to_read,
    set_resume_metadata,
)
from .services.profile_extractor import extract_profile_from_resume
from .services.resume_parser import extract_text_from_resume
from .schemas_nl import (
    NLJobExecuteRequest,
    NLJobExecuteResult,
    NLJobPlan,
    NLJobPlanRequest,
)
from .services.nl_job_agent import create_plan, execute_plan
from .services.search_agent import google_jobs_search_url, run_job_search

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/jobs", response_model=list[JobRead])
def list_jobs(
    status: JobStatus | None = None,
    q: str | None = Query(default=None, description="Search title/company/notes"),
    include_ignored: bool = Query(default=False, description="Include ignored jobs"),
    db: Session = Depends(get_db),
):
    query = db.query(Job).options(joinedload(Job.events)).order_by(Job.updated_at.desc())
    if status:
        query = query.filter(Job.status == status)
    elif not include_ignored:
        query = query.filter(Job.status != JobStatus.IGNORED)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Job.title.ilike(like)) | (Job.company.ilike(like)) | (Job.notes.ilike(like))
        )
    return [job_to_read(job) for job in query.all()]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.events))
        .filter(Job.id == job_id)
        .one_or_none()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_read(job)


@router.post("/jobs", response_model=JobRead)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    existing = db.query(Job).filter(Job.url == payload.url).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Job with this URL already exists")

    job = Job(**payload.model_dump())
    add_status_event(db, job, job.status, note="Added manually")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job_to_read(job)


@router.patch("/jobs/{job_id}", response_model=JobRead)
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = db.query(Job).options(joinedload(Job.events)).filter(Job.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    for key, value in data.items():
        setattr(job, key, value)

    if new_status and new_status != job.status:
        add_status_event(db, job, new_status, note="Status updated")

    db.commit()
    db.refresh(job)
    return job_to_read(job)


@router.post("/jobs/{job_id}/status", response_model=JobRead)
def update_status(job_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    job = db.query(Job).options(joinedload(Job.events)).filter(Job.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    add_status_event(db, job, payload.status, note=payload.note)
    db.commit()
    db.refresh(job)
    return job_to_read(job)


@router.post("/jobs/{job_id}/description/enrich", response_model=JobDescriptionEnrichResult)
async def enrich_job_description_route(job_id: int, db: Session = Depends(get_db)):
    try:
        return await enrich_job_description(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/fit", response_model=JobFitResult)
def analyze_fit(job_id: int, db: Session = Depends(get_db)):
    try:
        return analyze_job_fit(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/profile/apply", response_model=ApplyProfileRead)
def get_apply_profile(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    return read_apply_profile(profile)


@router.put("/profile/apply", response_model=ApplyProfileRead)
def put_apply_profile(payload: ApplyProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    result = update_apply_profile(profile, payload)
    db.commit()
    return result


@router.post("/profile/apply/extract-from-resume", response_model=ApplyProfileExtractResult)
def extract_apply_profile_from_stored_resume(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    if not profile.resume_filename:
        raise HTTPException(status_code=400, detail="Upload a resume first.")

    resume_path = RESUMES_DIR / profile.resume_filename
    if not resume_path.exists():
        raise HTTPException(status_code=404, detail="Resume file not found.")

    try:
        resume_text = extract_text_from_resume(profile.resume_filename, resume_path.read_bytes())
        apply_profile, method = populate_apply_profile_from_resume(profile, resume_text)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = (
        "Apply profile updated from resume with AI. Review and edit the fields below."
        if method == "openai"
        else "Apply profile updated from resume with basic extraction. Add OPENAI_API_KEY for richer results."
    )
    return ApplyProfileExtractResult(
        **apply_profile.model_dump(),
        extraction_method=method,
        message=message,
    )


@router.get("/jobs/{job_id}/apply", response_model=ApplyStatusRead)
def job_apply_status(job_id: int, db: Session = Depends(get_db)):
    try:
        return get_apply_status(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/apply/prepare", response_model=PrepareApplyResult)
def job_apply_prepare(job_id: int, db: Session = Depends(get_db)):
    try:
        return prepare_apply(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/apply/complete", response_model=JobRead)
def job_apply_complete(
    job_id: int,
    payload: CompleteApplyRequest,
    db: Session = Depends(get_db),
):
    try:
        job = complete_apply(db, job_id, payload.note)
        job = (
            db.query(Job)
            .options(joinedload(Job.events))
            .filter(Job.id == job.id)
            .one()
        )
        return job_to_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/apply/attempts", response_model=list[ApplyAttemptRead])
def job_apply_attempts(job_id: int, db: Session = Depends(get_db)):
    try:
        return list_apply_attempts(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/apply/fill-payload", response_model=ApplyFillPayload)
def job_apply_fill_payload(job_id: int, db: Session = Depends(get_db)):
    try:
        return get_fill_payload(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/apply/assist")
def job_apply_assist(job_id: int, db: Session = Depends(get_db)):
    try:
        return get_assist_url(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/apply/auto", response_model=AutoApplyResult)
async def job_apply_auto(
    job_id: int,
    payload: AutoApplyRequest,
    db: Session = Depends(get_db),
):
    import asyncio

    try:
        return await asyncio.to_thread(
            run_auto_apply,
            db,
            job_id,
            confirmed=payload.confirmed,
            submit=payload.submit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/apply/screenshot")
def job_apply_screenshot(job_id: int):
    for suffix in ("fill", "submit"):
        path = SCREENSHOTS_DIR / f"job_{job_id}_{suffix}.png"
        if path.exists():
            return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail="No screenshot found for this job.")


@router.get("/apply/match")
def apply_match(url: str = Query(...), db: Session = Depends(get_db)):
    job = find_job_by_url(db, url)
    if not job:
        return {"matched": False}
    profile = get_or_create_profile(db)
    payload = get_fill_payload(db, job.id)
    return {"matched": True, "job_id": job.id, "payload": payload}


@router.get("/profile/resume/file")
def download_resume_file(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    if not profile.resume_filename:
        raise HTTPException(status_code=404, detail="No resume on file.")
    resume_path = RESUMES_DIR / profile.resume_filename
    if not resume_path.exists():
        raise HTTPException(status_code=404, detail="Resume file not found.")
    return FileResponse(resume_path, filename=profile.resume_filename)


@router.delete("/jobs")
def delete_all_jobs(db: Session = Depends(get_db)):
    count = db.query(Job).count()
    if count:
        db.query(ApplyAttempt).delete(synchronize_session=False)
        db.query(JobEvent).delete(synchronize_session=False)
        db.query(Job).delete(synchronize_session=False)
        db.commit()
    return {"ok": True, "deleted": count}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.query(ApplyAttempt).filter(ApplyAttempt.job_id == job_id).delete(synchronize_session=False)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/agent/search", response_model=SearchResult)
async def search_jobs(payload: SearchRequest, db: Session = Depends(get_db)):
    result = await run_job_search(
        db,
        titles=payload.titles,
        keywords=payload.keywords,
        locations=payload.locations,
        skills=payload.skills,
        industries=payload.industries,
        exclude_keywords=payload.exclude_keywords,
        seniority=payload.seniority,
        max_results=payload.max_results,
    )
    return SearchResult(**result)


@router.get("/companies", response_model=list[TargetCompanyRead])
def list_companies(db: Session = Depends(get_db)):
    return db.query(TargetCompany).order_by(TargetCompany.name.asc()).all()


@router.post("/companies", response_model=TargetCompanyRead)
def create_company(payload: TargetCompanyCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    careers_url = payload.careers_url.strip()
    if not name or not careers_url:
        raise HTTPException(status_code=400, detail="Company name and careers URL are required.")

    parsed = parse_careers_url(careers_url)
    if parsed.ats_type == "unsupported":
        raise HTTPException(status_code=400, detail=parsed.message or "Unsupported careers URL.")

    company = TargetCompany(name=name, careers_url=careers_url)
    apply_parsed_company_fields(company, careers_url)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.patch("/companies/{company_id}", response_model=TargetCompanyRead)
def update_company(
    company_id: int,
    payload: TargetCompanyUpdate,
    db: Session = Depends(get_db),
):
    company = db.query(TargetCompany).filter(TargetCompany.id == company_id).one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        company.name = data["name"].strip()
    if "enabled" in data and data["enabled"] is not None:
        company.enabled = data["enabled"]
    if "careers_url" in data and data["careers_url"] is not None:
        careers_url = data["careers_url"].strip()
        parsed = parse_careers_url(careers_url)
        if parsed.ats_type == "unsupported":
            raise HTTPException(status_code=400, detail=parsed.message or "Unsupported careers URL.")
        apply_parsed_company_fields(company, careers_url)

    db.commit()
    db.refresh(company)
    return company


@router.delete("/companies/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = db.query(TargetCompany).filter(TargetCompany.id == company_id).one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    db.delete(company)
    db.commit()
    return {"ok": True}


@router.post("/agent/company-search", response_model=CompanySearchResult)
async def search_company_jobs(payload: SearchRequest, db: Session = Depends(get_db)):
    result = await run_company_search(
        db,
        titles=payload.titles,
        keywords=payload.keywords,
        locations=payload.locations,
        skills=payload.skills,
        exclude_keywords=payload.exclude_keywords,
        seniority=payload.seniority,
    )
    return CompanySearchResult(**result)


@router.post("/agent/nl-jobs/plan", response_model=NLJobPlan)
def plan_nl_job_action(payload: NLJobPlanRequest, db: Session = Depends(get_db)):
    try:
        return create_plan(db, payload.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/nl-jobs/execute", response_model=NLJobExecuteResult)
def execute_nl_job_action(payload: NLJobExecuteRequest, db: Session = Depends(get_db)):
    try:
        affected, message = execute_plan(db, payload.plan, payload.confirmed)
        return NLJobExecuteResult(
            action=payload.plan.action,
            affected_count=affected,
            message=message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/profile", response_model=SearchProfileRead)
def get_profile(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    return profile_to_read(profile)


@router.put("/profile", response_model=SearchProfileRead)
def update_profile(payload: SearchProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    apply_profile_data(profile, payload)
    db.commit()
    db.refresh(profile)
    return profile_to_read(profile)


@router.post("/profile/resume", response_model=ResumeUploadResult)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    content = await file.read()
    try:
        resume_text = extract_text_from_resume(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    extracted, method = extract_profile_from_resume(resume_text)

    safe_name = file.filename.replace("..", "").replace("/", "_").replace("\\", "_")
    resume_path = RESUMES_DIR / safe_name
    resume_path.write_bytes(content)

    profile = get_or_create_profile(db)
    apply_profile_data(profile, extracted)
    set_resume_metadata(profile, safe_name)

    apply_method = None
    try:
        _, apply_method = populate_apply_profile_from_resume(profile, resume_text)
    except ValueError:
        pass

    db.commit()
    db.refresh(profile)

    read = profile_to_read(profile)
    message = (
        "Resume analyzed with AI. Review and edit your search criteria below."
        if method == "openai"
        else "Resume analyzed with basic extraction. Add OPENAI_API_KEY for richer results."
    )
    if apply_method:
        message += (
            " Apply profile was also updated from your resume."
            if apply_method == "openai"
            else " Apply profile was updated with basic extraction — review Apply profile fields."
        )
    return ResumeUploadResult(
        **read.model_dump(),
        extraction_method=method,
        message=message,
    )


@router.delete("/profile/resume", response_model=SearchProfileRead)
def delete_resume(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    if profile.resume_filename:
        resume_path = RESUMES_DIR / profile.resume_filename
        if resume_path.exists():
            resume_path.unlink()
    profile.resume_filename = None
    profile.resume_uploaded_at = None
    db.commit()
    db.refresh(profile)
    return profile_to_read(profile)


@router.get("/agent/google-jobs-url")
def get_google_jobs_url(
    titles: str | None = None,
    keywords: str | None = None,
):
    title_list = [part.strip() for part in titles.split(",")] if titles else None
    keyword_list = [part.strip() for part in keywords.split(",")] if keywords else None
    return {"url": google_jobs_search_url(title_list, keyword_list)}


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)):
    jobs = (
        db.query(Job)
        .options(joinedload(Job.events))
        .filter(Job.status != JobStatus.IGNORED)
        .order_by(Job.updated_at.desc())
        .all()
    )
    by_status = {status.value: 0 for status in JobStatus if status != JobStatus.IGNORED}
    for job in jobs:
        by_status[job.status.value] += 1

    return DashboardStats(
        total=len(jobs),
        by_status=by_status,
        recent=[job_to_read(job) for job in jobs[:8]],
    )
