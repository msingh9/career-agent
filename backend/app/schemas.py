from datetime import datetime

from pydantic import BaseModel, Field

from .models import JobStatus


class JobEventRead(BaseModel):
    id: int
    status: JobStatus
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobBase(BaseModel):
    title: str
    company: str
    location: str | None = None
    url: str
    source: str = "manual"
    description: str | None = None
    description_summary: str | None = None
    description_enriched_at: datetime | None = None
    salary: str | None = None
    posted_date: str | None = None
    notes: str | None = None


class JobCreate(JobBase):
    status: JobStatus = JobStatus.NEW


class JobUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    description_summary: str | None = None
    description_enriched_at: datetime | None = None
    salary: str | None = None
    posted_date: str | None = None
    status: JobStatus | None = None
    notes: str | None = None


class JobRead(JobBase):
    id: int
    status: JobStatus
    discovered_at: datetime
    updated_at: datetime
    fit_score: int | None = None
    fit_verdict: str | None = None
    fit_summary: str | None = None
    fit_strengths: list[str] = Field(default_factory=list)
    fit_gaps: list[str] = Field(default_factory=list)
    fit_method: str | None = None
    fit_message: str | None = None
    fit_analyzed_at: datetime | None = None
    ats_coverage: int | None = None
    ats_missing_keywords: list[str] = Field(default_factory=list)
    apply_mode: str | None = None
    apply_confidence: int | None = None
    apply_prepared_at: datetime | None = None
    ats_type: str = "unsupported"
    auto_apply_supported: bool = False
    events: list[JobEventRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class JobDescriptionEnrichResult(BaseModel):
    job_id: int
    description: str | None = None
    description_summary: str
    description_enriched_at: datetime
    fetch_source: str
    summary_method: str
    message: str


class StatusUpdate(BaseModel):
    status: JobStatus
    note: str | None = None


class SearchRequest(BaseModel):
    titles: list[str] | None = None
    keywords: list[str] | None = None
    locations: list[str] | None = None
    skills: list[str] | None = None
    industries: list[str] | None = None
    exclude_keywords: list[str] | None = None
    seniority: str | None = None
    max_results: int = 50


class SearchResult(BaseModel):
    found: int
    added: int
    skipped: int
    message: str


class SearchProfileData(BaseModel):
    titles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    seniority: str | None = None
    exclude_keywords: list[str] = Field(default_factory=list)
    summary: str | None = None


class SearchProfileRead(SearchProfileData):
    resume_filename: str | None = None
    resume_uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    has_openai: bool = False
    match_strictness: int = 5


class SearchProfileUpdate(SearchProfileData):
    # Optional so resume-extraction updates never reset the user's chosen value.
    match_strictness: int | None = Field(default=None, ge=1, le=10)


class ResumeUploadResult(SearchProfileRead):
    extraction_method: str
    message: str


class DashboardStats(BaseModel):
    total: int
    by_status: dict[str, int]
    recent: list[JobRead]


class TargetCompanyCreate(BaseModel):
    name: str
    careers_url: str


class TargetCompanyUpdate(BaseModel):
    name: str | None = None
    careers_url: str | None = None
    enabled: bool | None = None


class TargetCompanyRead(BaseModel):
    id: int
    name: str
    careers_url: str
    ats_type: str
    board_token: str | None
    workday_host: str | None = None
    enabled: bool
    last_scraped_at: datetime | None
    last_job_count: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanySearchDetail(BaseModel):
    company: str
    ats_type: str
    found: int
    added: int
    skipped: int
    filtered: int
    error: str | None = None


class CompanySearchResult(SearchResult):
    companies_scanned: int = 0
    details: list[CompanySearchDetail] = Field(default_factory=list)


class JobFitResult(BaseModel):
    job_id: int
    score: int = Field(ge=0, le=100)
    verdict: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    method: str
    message: str | None = None
    analyzed_at: datetime
    ats_coverage: int | None = None
    ats_missing_keywords: list[str] = Field(default_factory=list)
