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

from ..models import SearchProfile
from ..schemas_apply import (
    ApplyIdentity,
    ApplyProfileRead,
    ApplyProfileUpdate,
    ApplySettings,
    SavedAnswer,
)

DEFAULT_SAVED_ANSWERS = [
    SavedAnswer(key="why_interested", label="Why are you interested in this role?"),
    SavedAnswer(key="leadership_style", label="Describe your leadership style"),
    SavedAnswer(key="compensation", label="Compensation expectations"),
    SavedAnswer(key="relocation", label="Relocation willingness"),
    SavedAnswer(key="work_authorization_detail", label="Work authorization details"),
]

REQUIRED_IDENTITY_FIELDS = ("full_name", "email")


def _merge_saved_answers(stored: list[SavedAnswer]) -> list[SavedAnswer]:
    by_key = {item.key: item for item in stored}
    merged: list[SavedAnswer] = []
    for default in DEFAULT_SAVED_ANSWERS:
        existing = by_key.pop(default.key, None)
        merged.append(existing or default)
    for item in by_key.values():
        merged.append(item)
    return merged


def _identity_missing_fields(identity: ApplyIdentity) -> list[str]:
    missing: list[str] = []
    if not identity.full_name.strip():
        missing.append("full_name")
    if not identity.email.strip():
        missing.append("email")
    return missing


def read_apply_profile(profile: SearchProfile) -> ApplyProfileRead:
    identity = ApplyIdentity.model_validate(profile.get_json_dict("apply_identity") or {})
    settings = ApplySettings.model_validate(profile.get_json_dict("apply_settings") or {})
    stored_answers = [
        SavedAnswer.model_validate(item) for item in profile.get_json_list("apply_saved_answers")
    ]
    saved_answers = _merge_saved_answers(stored_answers)
    missing_fields = _identity_missing_fields(identity)
    if not profile.resume_filename:
        missing_fields.append("resume")

    return ApplyProfileRead(
        identity=identity,
        saved_answers=saved_answers,
        settings=settings,
        profile_complete=len(missing_fields) == 0,
        missing_fields=missing_fields,
    )


def update_apply_profile(profile: SearchProfile, payload: ApplyProfileUpdate) -> ApplyProfileRead:
    if payload.identity is not None:
        profile.set_json_dict("apply_identity", payload.identity.model_dump())
    if payload.settings is not None:
        profile.set_json_dict("apply_settings", payload.settings.model_dump())
    if payload.saved_answers is not None:
        profile.set_json_list(
            "apply_saved_answers",
            [item.model_dump() for item in _merge_saved_answers(payload.saved_answers)],
        )
    return read_apply_profile(profile)


def apply_extracted_apply_profile(
    profile: SearchProfile,
    extracted: ApplyProfileUpdate,
) -> ApplyProfileRead:
    """Persist extracted apply profile while preserving user settings."""
    current = read_apply_profile(profile)
    if extracted.identity is not None:
        profile.set_json_dict("apply_identity", extracted.identity.model_dump())
    if extracted.saved_answers is not None:
        profile.set_json_list(
            "apply_saved_answers",
            [item.model_dump() for item in _merge_saved_answers(extracted.saved_answers)],
        )
    settings = current.settings
    profile.set_json_dict("apply_settings", settings.model_dump())
    return read_apply_profile(profile)


def populate_apply_profile_from_resume(
    profile: SearchProfile,
    resume_text: str,
) -> tuple[ApplyProfileRead, str]:
    from .apply_profile_extractor import extract_apply_profile_from_resume

    current = read_apply_profile(profile)
    extracted, method = extract_apply_profile_from_resume(resume_text, current)
    updated = apply_extracted_apply_profile(profile, extracted)
    return updated, method


def identity_is_complete(identity: ApplyIdentity) -> bool:
    return not _identity_missing_fields(identity)
