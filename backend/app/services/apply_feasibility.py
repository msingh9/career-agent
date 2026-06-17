from urllib.parse import urlparse

from ..models import Job, SearchProfile
from ..schemas_apply import ApplyFeasibility, ApplyIdentity, ApplyMode, ApplySettings
from .apply_profile import identity_is_complete, read_apply_profile
from .ats_parser import parse_careers_url

LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com"}
INDEED_HOSTS = {"indeed.com", "www.indeed.com"}

ATS_BASE_SCORES: dict[str, tuple[ApplyMode, int]] = {
    "greenhouse": ("assisted", 72),
    "lever": ("assisted", 70),
    "workday": ("manual_only", 38),
    "unsupported": ("manual_only", 42),
}


def _detect_ats_from_url(url: str) -> tuple[str, str | None]:
    host = urlparse(url).netloc.lower()
    if any(linkedin in host for linkedin in LINKEDIN_HOSTS):
        return "linkedin", None
    if any(indeed in host for indeed in INDEED_HOSTS):
        return "indeed", None

    parsed = parse_careers_url(url)
    return parsed.ats_type, parsed.message


def _mode_from_confidence(
    base_mode: ApplyMode,
    confidence: int,
    settings: ApplySettings,
) -> ApplyMode:
    if confidence < 60:
        return "manual_only"
    if confidence < 85:
        return "assisted" if base_mode != "manual_only" else "manual_only"
    if not settings.auto_apply_enabled:
        return "assisted" if base_mode != "manual_only" else "manual_only"
    if settings.always_confirm_submit:
        return "auto_with_review"
    return "auto"


def assess_apply_feasibility(
    job: Job,
    profile: SearchProfile,
    identity: ApplyIdentity | None = None,
    settings: ApplySettings | None = None,
) -> ApplyFeasibility:
    apply_profile = read_apply_profile(profile)
    identity = identity or apply_profile.identity
    settings = settings or apply_profile.settings

    ats_type, parse_message = _detect_ats_from_url(job.url)
    base_mode, confidence = ATS_BASE_SCORES.get(ats_type, ("manual_only", 40))
    reasons: list[str] = []

    if ats_type == "greenhouse":
        reasons.append("Greenhouse posting detected — assisted apply with copy-ready materials.")
    elif ats_type == "lever":
        reasons.append("Lever posting detected — assisted apply with copy-ready materials.")
    elif ats_type == "workday":
        reasons.append("Workday posting detected — high form variability; manual apply recommended.")
        confidence -= 8
    elif ats_type == "linkedin":
        reasons.append("LinkedIn posting — login and custom flow required; manual apply only.")
        confidence = min(confidence, 30)
        base_mode = "manual_only"
    elif ats_type == "indeed":
        reasons.append("Indeed posting — apply flow varies; manual apply only.")
        confidence = min(confidence, 35)
        base_mode = "manual_only"
    else:
        reasons.append("Unknown or custom ATS — manual apply with prepared materials.")

    if parse_message and ats_type == "unsupported":
        reasons.append(parse_message)

    description = (job.description or "").strip()
    if len(description) >= 200:
        confidence += 5
        reasons.append("Job description available for tailoring.")
    elif description:
        confidence -= 5
        reasons.append("Short job description — open the posting for full requirements.")
    else:
        confidence -= 10
        reasons.append("No job description stored — review the live posting before applying.")

    if profile.resume_filename:
        confidence += 10
    else:
        confidence -= 12
        reasons.append("Upload a resume to improve apply preparation.")

    if identity_is_complete(identity):
        confidence += 12
    else:
        confidence -= 15
        reasons.append("Add your name and email in Apply profile.")

    if identity.phone.strip():
        confidence += 3
    if identity.linkedin_url.strip():
        confidence += 3

    confidence = max(0, min(100, confidence))
    apply_mode = _mode_from_confidence(base_mode, confidence, settings)
    can_auto_submit = (
        ats_type in {"greenhouse", "lever"}
        and apply_mode in {"auto", "auto_with_review"}
        and confidence >= settings.min_auto_confidence
    )

    if can_auto_submit:
        recommended_action = (
            "High-confidence Greenhouse/Lever posting. You can use browser assist fill or auto-apply with confirmation."
        )
    elif apply_mode == "assisted":
        recommended_action = (
            "Use browser assist fill on the posting, or copy materials and submit manually."
        )
    else:
        recommended_action = "Prepare materials, open the posting, and complete the application manually."

    return ApplyFeasibility(
        ats_type=ats_type,
        apply_mode=apply_mode,
        confidence=confidence,
        reasons=reasons,
        recommended_action=recommended_action,
        can_auto_submit=can_auto_submit,
    )
