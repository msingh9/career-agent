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

import re
from dataclasses import dataclass
from urllib.parse import urlparse

LOCALE_PREFIX = re.compile(r"^[a-z]{2}-[A-Z]{2}$")

GREENHOUSE_PATTERNS = [
    re.compile(r"boards\.greenhouse\.io/(?P<token>[a-zA-Z0-9_-]+)", re.I),
    re.compile(r"job-boards\.greenhouse\.io/(?P<token>[a-zA-Z0-9_-]+)", re.I),
    re.compile(r"boards-api\.greenhouse\.io/v1/boards/(?P<token>[a-zA-Z0-9_-]+)", re.I),
    re.compile(r"greenhouse\.io/(?P<token>[a-zA-Z0-9_-]+)/", re.I),
]

LEVER_PATTERNS = [
    re.compile(r"jobs\.lever\.co/(?P<token>[a-zA-Z0-9_-]+)", re.I),
    re.compile(r"api\.lever\.co/v0/postings/(?P<token>[a-zA-Z0-9_-]+)", re.I),
]

WORKDAY_HOST_PATTERN = re.compile(
    r"(?P<tenant>[a-z0-9_-]+)\.wd\d+\.myworkdayjobs\.com",
    re.I,
)


@dataclass
class ParsedCareersUrl:
    ats_type: str
    board_token: str | None
    workday_host: str | None = None
    message: str | None = None


def _normalize_input(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    return text


def _workday_site_from_path(path: str) -> str | None:
    parts = [part for part in path.strip("/").split("/") if part]
    if parts and LOCALE_PREFIX.match(parts[0]):
        parts = parts[1:]
    return parts[0] if parts else None


def parse_workday_url(normalized: str) -> ParsedCareersUrl | None:
    parsed = urlparse(normalized)
    host = parsed.netloc.lower()
    if "myworkdayjobs.com" not in host:
        return None

    host_match = WORKDAY_HOST_PATTERN.search(host)
    if not host_match:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Workday host could not be parsed. Use a myworkdayjobs.com careers URL.",
        )

    site = _workday_site_from_path(parsed.path)
    if not site:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Workday site name missing from URL. Include the career site path.",
        )

    return ParsedCareersUrl(
        ats_type="workday",
        board_token=site,
        workday_host=host,
    )


def parse_careers_url(value: str) -> ParsedCareersUrl:
    normalized = _normalize_input(value)
    if not normalized:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Careers URL is required.",
        )

    for pattern in GREENHOUSE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return ParsedCareersUrl(ats_type="greenhouse", board_token=match.group("token"))

    for pattern in LEVER_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return ParsedCareersUrl(ats_type="lever", board_token=match.group("token"))

    workday = parse_workday_url(normalized)
    if workday:
        return workday

    host = urlparse(normalized).netloc.lower()
    if "greenhouse" in host:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Greenhouse URL detected but board token could not be parsed. Use a boards.greenhouse.io link.",
        )
    if "lever" in host:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Lever URL detected but company slug could not be parsed. Use a jobs.lever.co link.",
        )
    if "myworkdayjobs.com" in host:
        return ParsedCareersUrl(
            ats_type="unsupported",
            board_token=None,
            message="Workday URL detected but career site could not be parsed.",
        )

    return ParsedCareersUrl(
        ats_type="unsupported",
        board_token=None,
        message="Supported ATS types: Greenhouse, Lever, and Workday career pages.",
    )


def workday_tenant_from_host(workday_host: str | None) -> str | None:
    if not workday_host:
        return None
    match = WORKDAY_HOST_PATTERN.search(workday_host.lower())
    return match.group("tenant") if match else None
