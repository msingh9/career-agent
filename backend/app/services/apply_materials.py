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

import json

from openai import OpenAI

from ..config import settings
from ..models import Job, SearchProfile
from ..schemas_apply import (
    ApplyChecklistItem,
    ApplyIdentity,
    ApplyKit,
    ApplyMaterialAnswer,
    ApplyMaterials,
    SavedAnswer,
)
from .apply_profile import read_apply_profile
from .job_fit import load_stored_resume_text

SYSTEM_PROMPT = """You prepare job application materials for a candidate.

Rules:
- Write concise, professional content suitable for senior roles
- Do not invent employers, degrees, or metrics not supported by the resume/profile
- Return JSON only
- Application is always submitted manually by the user

Return:
{
  "cover_letter": "short tailored cover letter",
  "outreach_email": "short recruiter/hiring manager outreach email",
  "why_this_role": "2-3 sentence why-this-role answer",
  "answers": [
    {"question": "question text", "answer": "tailored answer"}
  ]
}
"""


def _default_checklist() -> list[ApplyChecklistItem]:
    return [
        ApplyChecklistItem(id="review_fit", label="Review fit analysis"),
        ApplyChecklistItem(id="prepare_materials", label="Prepare tailored application materials"),
        ApplyChecklistItem(id="open_posting", label="Open the job posting"),
        ApplyChecklistItem(id="submit_application", label="Submit application on company site"),
        ApplyChecklistItem(id="mark_applied", label="Mark applied in tracker"),
    ]


def _copy_fields(identity: ApplyIdentity) -> dict[str, str]:
    fields = {
        "full_name": identity.full_name,
        "email": identity.email,
        "phone": identity.phone,
        "linkedin_url": identity.linkedin_url,
        "website": identity.website,
        "location": identity.location,
        "work_authorization": identity.work_authorization,
        "requires_sponsorship": "Yes" if identity.requires_sponsorship else "No",
    }
    return {key: value for key, value in fields.items() if value}


def _template_materials(
    job: Job,
    profile: SearchProfile,
    saved_answers: list[SavedAnswer],
) -> ApplyMaterials:
    apply_profile = read_apply_profile(profile)
    summary = profile.summary or "my background"
    company = job.company
    title = job.title

    cover_letter = (
        f"I am interested in the {title} role at {company}. "
        f"My background aligns with this opportunity: {summary[:280]}"
    )
    outreach_email = (
        f"Hello — I am interested in the {title} opening at {company}. "
        f"I would welcome a brief conversation about how my experience may fit your team."
    )
    why_this_role = (
        f"This {title} role at {company} aligns with my experience and career goals. "
        f"I am especially interested in opportunities where I can contribute immediately."
    )

    answers: list[ApplyMaterialAnswer] = []
    for item in saved_answers:
        if not item.answer.strip():
            continue
        answers.append(ApplyMaterialAnswer(question=item.label, answer=item.answer))

    if not answers:
        answers.append(
            ApplyMaterialAnswer(
                question="Why are you interested in this role?",
                answer=why_this_role,
            )
        )

    return ApplyMaterials(
        cover_letter=cover_letter,
        outreach_email=outreach_email,
        why_this_role=why_this_role,
        answers=answers,
    )


def _build_prompt(
    job: Job,
    profile: SearchProfile,
    identity: ApplyIdentity,
    saved_answers: list[SavedAnswer],
    resume_text: str | None,
) -> str:
    answer_lines = "\n".join(
        f"- {item.label}: {item.answer}" for item in saved_answers if item.answer.strip()
    )
    return f"""Job:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or "Not listed"}
- Description:
{(job.description or "Not available")[:6000]}

Candidate:
- Summary: {profile.summary or "Not set"}
- Skills: {", ".join(profile.get_list("skills"))}
- Titles: {", ".join(profile.get_list("titles"))}
- Identity: {identity.full_name}, {identity.email}, {identity.location}

Saved answers:
{answer_lines or "None"}

Resume excerpt:
{(resume_text or "No resume on file")[:8000]}
"""


def _openai_materials(
    job: Job,
    profile: SearchProfile,
    identity: ApplyIdentity,
    saved_answers: list[SavedAnswer],
    resume_text: str | None,
) -> ApplyMaterials:
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(job, profile, identity, saved_answers, resume_text)},
        ],
    )
    data = json.loads(response.choices[0].message.content or "{}")
    answers = [
        ApplyMaterialAnswer(
            question=str(item.get("question", "")).strip(),
            answer=str(item.get("answer", "")).strip(),
        )
        for item in data.get("answers", [])
        if str(item.get("answer", "")).strip()
    ]
    return ApplyMaterials(
        cover_letter=str(data.get("cover_letter", "")).strip(),
        outreach_email=str(data.get("outreach_email", "")).strip(),
        why_this_role=str(data.get("why_this_role", "")).strip(),
        answers=answers,
    )


def build_apply_kit(job: Job, profile: SearchProfile) -> ApplyKit:
    apply_profile = read_apply_profile(profile)
    identity = apply_profile.identity
    saved_answers = apply_profile.saved_answers
    resume_text = load_stored_resume_text(profile)

    if settings.openai_api_key:
        try:
            materials = _openai_materials(job, profile, identity, saved_answers, resume_text)
        except Exception:
            materials = _template_materials(job, profile, saved_answers)
    else:
        materials = _template_materials(job, profile, saved_answers)

    if not materials.cover_letter:
        materials = _template_materials(job, profile, saved_answers)

    return ApplyKit(
        checklist=_default_checklist(),
        materials=materials,
        copy_fields=_copy_fields(identity),
    )
