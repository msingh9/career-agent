from pydantic import BaseModel, Field


class JobQueryFilters(BaseModel):
    company_contains: list[str] = Field(default_factory=list)
    company_excludes: list[str] = Field(default_factory=list)
    title_contains: list[str] = Field(default_factory=list)
    title_excludes: list[str] = Field(default_factory=list)
    location_contains: list[str] = Field(default_factory=list)
    source_in: list[str] = Field(default_factory=list)
    status_in: list[str] = Field(default_factory=list)
    status_not_in: list[str] = Field(default_factory=list)
    notes_contains: list[str] = Field(default_factory=list)
    senior_executive_only: bool = False
    non_senior_only: bool = False


class JobQueryUpdate(BaseModel):
    status: str | None = None
    notes_append: str | None = None


class JobPreview(BaseModel):
    id: int
    title: str
    company: str
    location: str | None
    status: str
    source: str


class NLJobPlanRequest(BaseModel):
    query: str


class NLJobPlan(BaseModel):
    action: str
    explanation: str
    filters: JobQueryFilters
    update: JobQueryUpdate | None = None
    sql_preview: str
    requires_confirmation: bool
    affected_count: int
    preview_jobs: list[JobPreview] = Field(default_factory=list)


class NLJobExecuteRequest(BaseModel):
    plan: NLJobPlan
    confirmed: bool = False


class NLJobExecuteResult(BaseModel):
    action: str
    affected_count: int
    message: str
