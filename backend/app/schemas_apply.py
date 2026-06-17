from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ApplyMode = Literal["manual_only", "assisted", "auto_with_review", "auto"]
ApplyAttemptStatus = Literal[
    "prepared",
    "manual_started",
    "filled",
    "submitted",
    "completed",
    "failed",
    "cancelled",
]


class SavedAnswer(BaseModel):
    key: str
    label: str
    answer: str = ""


class ApplyIdentity(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    website: str = ""
    location: str = ""
    work_authorization: str = ""
    requires_sponsorship: bool = False


class ApplySettings(BaseModel):
    auto_apply_enabled: bool = False
    min_auto_confidence: int = Field(default=85, ge=60, le=100)
    always_confirm_submit: bool = True


class ApplyProfileRead(BaseModel):
    identity: ApplyIdentity = Field(default_factory=ApplyIdentity)
    saved_answers: list[SavedAnswer] = Field(default_factory=list)
    settings: ApplySettings = Field(default_factory=ApplySettings)
    profile_complete: bool = False
    missing_fields: list[str] = Field(default_factory=list)


class ApplyProfileUpdate(BaseModel):
    identity: ApplyIdentity | None = None
    saved_answers: list[SavedAnswer] | None = None
    settings: ApplySettings | None = None


class ApplyProfileExtractResult(ApplyProfileRead):
    extraction_method: str
    message: str


class ApplyChecklistItem(BaseModel):
    id: str
    label: str
    done: bool = False


class ApplyMaterialAnswer(BaseModel):
    question: str
    answer: str


class ApplyMaterials(BaseModel):
    cover_letter: str = ""
    outreach_email: str = ""
    why_this_role: str = ""
    answers: list[ApplyMaterialAnswer] = Field(default_factory=list)


class ApplyKit(BaseModel):
    checklist: list[ApplyChecklistItem] = Field(default_factory=list)
    materials: ApplyMaterials = Field(default_factory=ApplyMaterials)
    copy_fields: dict[str, str] = Field(default_factory=dict)


class ApplyFeasibility(BaseModel):
    ats_type: str
    apply_mode: ApplyMode
    confidence: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommended_action: str
    can_auto_submit: bool = False


class ApplyStatusRead(BaseModel):
    job_id: int
    feasibility: ApplyFeasibility
    kit: ApplyKit | None = None
    prepared_at: datetime | None = None
    latest_attempt_status: ApplyAttemptStatus | None = None


class PrepareApplyResult(BaseModel):
    job_id: int
    feasibility: ApplyFeasibility
    kit: ApplyKit
    prepared_at: datetime
    attempt_id: int
    message: str


class CompleteApplyRequest(BaseModel):
    note: str | None = None


class ApplyAttemptRead(BaseModel):
    id: int
    job_id: int
    mode: ApplyMode
    status: ApplyAttemptStatus
    confidence: int
    ats_type: str
    message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplyFillAnswer(BaseModel):
    question: str
    answer: str


class ApplyFillPayload(BaseModel):
    job_id: int
    job_title: str
    company: str
    job_url: str
    ats_type: str
    apply_mode: ApplyMode
    confidence: int
    can_auto_submit: bool
    fields: dict[str, str]
    answers: list[ApplyFillAnswer] = Field(default_factory=list)
    resume_available: bool = False
    resume_filename: str | None = None


class AutoApplyRequest(BaseModel):
    confirmed: bool = False
    submit: bool = True


class AutoApplyResult(BaseModel):
    job_id: int
    status: str
    message: str
    filled_fields: list[str] = Field(default_factory=list)
    submitted: bool = False
    attempt_id: int | None = None
    screenshot_path: str | None = None
