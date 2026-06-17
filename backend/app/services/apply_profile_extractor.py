import json
import re

from openai import OpenAI

from ..config import settings
from ..schemas_apply import ApplyIdentity, ApplyProfileRead, ApplyProfileUpdate, SavedAnswer
from .apply_profile import DEFAULT_SAVED_ANSWERS, _merge_saved_answers

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}\b"
)
LINKEDIN_PATTERN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?",
    re.I,
)
URL_PATTERN = re.compile(r"https?://[^\s)>\"]+", re.I)

SYSTEM_PROMPT = """You extract and draft job application profile fields from a resume.

The user may already have partial apply-profile data. Use the resume as the primary source.
Use existing apply-profile values as hints when the resume is ambiguous, but correct them when the resume clearly differs.

Return JSON only:
{
  "identity": {
    "full_name": "",
    "email": "",
    "phone": "",
    "linkedin_url": "",
    "website": "",
    "location": "",
    "work_authorization": "",
    "requires_sponsorship": false
  },
  "saved_answers": [
    {"key": "why_interested", "label": "Why are you interested in this role?", "answer": ""},
    {"key": "leadership_style", "label": "Describe your leadership style", "answer": ""},
    {"key": "compensation", "label": "Compensation expectations", "answer": ""},
    {"key": "relocation", "label": "Relocation willingness", "answer": ""},
    {"key": "work_authorization_detail", "label": "Work authorization details", "answer": ""}
  ]
}

Rules:
- identity fields must come from the resume when present (name, email, phone, LinkedIn, location)
- work_authorization: infer only if stated (e.g. US citizen, H1B, green card); otherwise keep existing or leave empty
- requires_sponsorship: true only if resume indicates visa sponsorship need
- saved_answers: write concise, professional, first-person application answers grounded in the resume
- do not invent employers, degrees, metrics, or authorization status not supported by the resume
- keep each saved answer under 120 words unless the resume strongly supports more detail
"""


def _build_user_prompt(resume_text: str, current: ApplyProfileRead) -> str:
    current_payload = {
        "identity": current.identity.model_dump(),
        "saved_answers": [item.model_dump() for item in current.saved_answers],
    }
    return f"""Current apply profile (for context — update from resume where appropriate):
{json.dumps(current_payload, indent=2)}

Resume:
{resume_text[:12000]}
"""


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(0).strip() if match else ""


def _guess_name(lines: list[str]) -> str:
    for line in lines[:8]:
        cleaned = line.strip()
        if not cleaned or "@" in cleaned or "http" in cleaned.lower():
            continue
        if len(cleaned.split()) <= 5 and re.search(r"[A-Za-z]", cleaned):
            if not re.search(r"\b(engineer|director|manager|resume|curriculum|phone|email)\b", cleaned, re.I):
                return cleaned
    return ""


def _guess_location(text: str) -> str:
    for pattern in (
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*(?:CA|TX|NY|WA|OR|AZ|CO|MA|IL|FL|GA|NC|NJ|VA|PA))\b",
        r"\b(San Francisco|San Jose|Los Angeles|Austin|Seattle|Portland|Boston|New York)\b",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return ""


def _heuristic_extract(resume_text: str, current: ApplyProfileRead) -> ApplyProfileUpdate:
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    email = _first_match(EMAIL_PATTERN, resume_text) or current.identity.email
    phone = _first_match(PHONE_PATTERN, resume_text) or current.identity.phone
    linkedin = _first_match(LINKEDIN_PATTERN, resume_text) or current.identity.linkedin_url
    full_name = _guess_name(lines) or current.identity.full_name
    location = _guess_location(resume_text) or current.identity.location

    website = current.identity.website
    for url in URL_PATTERN.findall(resume_text):
        lower = url.lower()
        if "linkedin.com" in lower:
            continue
        website = url.rstrip(".,)")
        break

    summary_bits = " ".join(lines[:12])[:500]
    current_by_key = {item.key: item for item in current.saved_answers}
    saved_answers = _merge_saved_answers(
        [
            SavedAnswer(
                key="why_interested",
                label="Why are you interested in this role?",
                answer=current_by_key.get("why_interested", SavedAnswer(key="why_interested", label="")).answer
                or f"I am interested in senior leadership roles where I can apply my experience in {summary_bits[:120]}...",
            ),
            SavedAnswer(
                key="leadership_style",
                label="Describe your leadership style",
                answer=current_by_key.get("leadership_style", SavedAnswer(key="leadership_style", label="")).answer
                or "I lead cross-functional engineering teams with a focus on execution, clarity, and technical depth.",
            ),
            SavedAnswer(
                key="work_authorization_detail",
                label="Work authorization details",
                answer=current_by_key.get("work_authorization_detail", SavedAnswer(key="work_authorization_detail", label="")).answer
                or current.identity.work_authorization,
            ),
        ]
    )

    return ApplyProfileUpdate(
        identity=ApplyIdentity(
            full_name=full_name,
            email=email,
            phone=phone,
            linkedin_url=linkedin,
            website=website,
            location=location,
            work_authorization=current.identity.work_authorization,
            requires_sponsorship=current.identity.requires_sponsorship,
        ),
        saved_answers=saved_answers,
    )


def _normalize_saved_answers(raw_answers: list) -> list[SavedAnswer]:
    by_key: dict[str, SavedAnswer] = {}
    for item in raw_answers:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        label = str(item.get("label", "")).strip() or key
        answer = str(item.get("answer", "")).strip()
        by_key[key] = SavedAnswer(key=key, label=label, answer=answer)

    merged: list[SavedAnswer] = []
    for default in DEFAULT_SAVED_ANSWERS:
        merged.append(by_key.get(default.key, default))
    for key, item in by_key.items():
        if key not in {default.key for default in DEFAULT_SAVED_ANSWERS}:
            merged.append(item)
    return merged


def _merge_extracted_answers(
    current: list[SavedAnswer],
    extracted: list[SavedAnswer],
) -> list[SavedAnswer]:
    current_by_key = {item.key: item for item in current}
    merged: list[SavedAnswer] = []
    for item in _merge_saved_answers(extracted):
        if not item.answer.strip():
            previous = current_by_key.get(item.key)
            if previous and previous.answer.strip():
                item = SavedAnswer(key=item.key, label=item.label, answer=previous.answer)
        merged.append(item)
    return _merge_saved_answers(merged)


def extract_apply_profile_from_resume(
    resume_text: str,
    current: ApplyProfileRead,
) -> tuple[ApplyProfileUpdate, str]:
    trimmed = resume_text.strip()
    if not trimmed:
        raise ValueError("Resume text is empty.")

    if settings.openai_api_key:
        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(trimmed, current)},
                ],
            )
            data = json.loads(response.choices[0].message.content or "{}")
            identity_data = data.get("identity") or {}
            merged_identity = {**current.identity.model_dump()}
            for key, value in identity_data.items():
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                merged_identity[key] = value
            identity = ApplyIdentity.model_validate(merged_identity)
            saved_answers = _merge_extracted_answers(
                current.saved_answers,
                _normalize_saved_answers(data.get("saved_answers") or []),
            )
            return ApplyProfileUpdate(identity=identity, saved_answers=saved_answers), "openai"
        except Exception:
            pass

    return _heuristic_extract(trimmed, current), "heuristic"
