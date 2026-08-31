# Copyright 2026 Manish Singh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import enum
import json
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class JobStatus(str, enum.Enum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPLIED = "applied"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    PASSED = "passed"
    IGNORED = "ignored"


class ApplyMode(str, enum.Enum):
    MANUAL_ONLY = "manual_only"
    ASSISTED = "assisted"
    AUTO_WITH_REVIEW = "auto_with_review"
    AUTO = "auto"


class ApplyAttemptStatus(str, enum.Enum):
    PREPARED = "prepared"
    MANUAL_STARTED = "manual_started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(1000), index=True)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    description: Mapped[str | None] = mapped_column(Text)
    description_summary: Mapped[str | None] = mapped_column(Text)
    description_enriched_at: Mapped[datetime | None] = mapped_column(DateTime)
    salary: Mapped[str | None] = mapped_column(String(200))
    posted_date: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.NEW, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    fit_score: Mapped[int | None] = mapped_column(Integer)
    fit_verdict: Mapped[str | None] = mapped_column(String(50))
    fit_summary: Mapped[str | None] = mapped_column(Text)
    fit_strengths: Mapped[str | None] = mapped_column(Text)
    fit_gaps: Mapped[str | None] = mapped_column(Text)
    fit_method: Mapped[str | None] = mapped_column(String(30))
    fit_message: Mapped[str | None] = mapped_column(Text)
    fit_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    ats_coverage: Mapped[int | None] = mapped_column(Integer)
    ats_missing: Mapped[str | None] = mapped_column(Text)
    apply_mode: Mapped[str | None] = mapped_column(String(30))
    apply_confidence: Mapped[int | None] = mapped_column(Integer)
    apply_reasons: Mapped[str | None] = mapped_column(Text)
    apply_kit: Mapped[str | None] = mapped_column(Text)
    apply_prepared_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "url", name="uq_jobs_user_url"),
    )

    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.created_at"
    )
    apply_attempts: Mapped[list["ApplyAttempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ApplyAttempt.created_at"
    )

    def get_json_dict(self, field: str) -> dict:
        raw = getattr(self, field, None)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def set_json_dict(self, field: str, value: dict) -> None:
        setattr(self, field, json.dumps(value))

    def get_fit_list(self, field: str) -> list[str]:
        raw = getattr(self, field, None)
        if not raw:
            return []
        try:
            value = json.loads(raw)
            return [str(item).strip() for item in value if str(item).strip()]
        except json.JSONDecodeError:
            return []

    def set_fit_list(self, field: str, values: list[str]) -> None:
        cleaned = [item.strip() for item in values if item and item.strip()]
        setattr(self, field, json.dumps(cleaned))


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="events")


class ApplyAttempt(Base):
    __tablename__ = "apply_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    ats_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="apply_attempts")


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    titles: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    keywords: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    locations: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    skills: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    industries: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    seniority: Mapped[str | None] = mapped_column(String(200))
    exclude_keywords: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    match_strictness: Mapped[int] = mapped_column(Integer, default=5, server_default="5", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    resume_filename: Mapped[str | None] = mapped_column(String(500))
    resume_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    apply_identity: Mapped[str | None] = mapped_column(Text)
    apply_saved_answers: Mapped[str | None] = mapped_column(Text)
    apply_settings: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def get_list(self, field: str) -> list[str]:
        raw = getattr(self, field, "[]") or "[]"
        try:
            value = json.loads(raw)
            return [str(item).strip() for item in value if str(item).strip()]
        except json.JSONDecodeError:
            return []

    def set_list(self, field: str, values: list[str]) -> None:
        cleaned = [item.strip() for item in values if item and item.strip()]
        setattr(self, field, json.dumps(cleaned))

    def get_json_dict(self, field: str) -> dict:
        raw = getattr(self, field, None)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def set_json_dict(self, field: str, value: dict) -> None:
        setattr(self, field, json.dumps(value))

    def get_json_list(self, field: str) -> list:
        raw = getattr(self, field, None)
        if not raw:
            return []
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    def set_json_list(self, field: str, values: list) -> None:
        setattr(self, field, json.dumps(values))


class TargetCompany(Base):
    __tablename__ = "target_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    careers_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    ats_type: Mapped[str] = mapped_column(String(50), default="unsupported", nullable=False)
    board_token: Mapped[str | None] = mapped_column(String(200))
    workday_host: Mapped[str | None] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_job_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
