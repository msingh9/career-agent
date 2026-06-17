from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import SearchProfile
from ..schemas import SearchProfileData, SearchProfileRead


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def default_profile_data() -> SearchProfileData:
    return SearchProfileData(
        titles=_parse_csv(settings.search_titles),
        keywords=_parse_csv(settings.search_keywords),
        locations=_parse_csv(settings.search_locations),
        skills=[],
        industries=["semiconductors"],
        seniority=None,
        exclude_keywords=[],
        summary=None,
    )


def get_or_create_profile(db: Session) -> SearchProfile:
    profile = db.query(SearchProfile).filter(SearchProfile.id == 1).one_or_none()
    if profile:
        return profile

    defaults = default_profile_data()
    profile = SearchProfile(id=1)
    profile.set_list("titles", defaults.titles)
    profile.set_list("keywords", defaults.keywords)
    profile.set_list("locations", defaults.locations)
    profile.set_list("skills", defaults.skills)
    profile.set_list("industries", defaults.industries)
    profile.set_list("exclude_keywords", defaults.exclude_keywords)
    profile.seniority = defaults.seniority
    profile.summary = defaults.summary
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def profile_to_read(profile: SearchProfile) -> SearchProfileRead:
    return SearchProfileRead(
        titles=profile.get_list("titles"),
        keywords=profile.get_list("keywords"),
        locations=profile.get_list("locations"),
        skills=profile.get_list("skills"),
        industries=profile.get_list("industries"),
        seniority=profile.seniority,
        exclude_keywords=profile.get_list("exclude_keywords"),
        summary=profile.summary,
        resume_filename=profile.resume_filename,
        resume_uploaded_at=profile.resume_uploaded_at,
        updated_at=profile.updated_at,
        has_openai=bool(settings.openai_api_key),
    )


def apply_profile_data(profile: SearchProfile, data: SearchProfileData) -> None:
    profile.set_list("titles", data.titles)
    profile.set_list("keywords", data.keywords)
    profile.set_list("locations", data.locations)
    profile.set_list("skills", data.skills)
    profile.set_list("industries", data.industries)
    profile.set_list("exclude_keywords", data.exclude_keywords)
    profile.seniority = data.seniority
    profile.summary = data.summary
    profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def set_resume_metadata(profile: SearchProfile, filename: str) -> None:
    profile.resume_filename = filename
    profile.resume_uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
