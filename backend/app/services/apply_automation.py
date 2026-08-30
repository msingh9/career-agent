"""Playwright-based auto-fill and optional submit for Tier A ATS (Greenhouse, Lever)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from ..database import DATA_DIR, RESUMES_DIR
from ..models import Job, SearchProfile
from ..schemas_apply import ApplyFillPayload
from .apply_fill_payload import build_fill_payload

SCREENSHOTS_DIR = DATA_DIR / "apply_screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_AUTO_ATS = {"greenhouse", "lever"}


@dataclass
class AutomationResult:
    success: bool
    status: str
    message: str
    filled_fields: list[str] = field(default_factory=list)
    submitted: bool = False
    screenshot_path: str | None = None


def _set_input(page, selectors: list[str], value: str) -> bool:
    if not value:
        return False
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.fill(value, timeout=3000)
            return True
        except Exception:
            continue
    return False


def _fill_textareas_by_keywords(page, answers: list[dict[str, str]]) -> list[str]:
    filled: list[str] = []
    textareas = page.locator("textarea")
    count = textareas.count()
    for index in range(count):
        textarea = textareas.nth(index)
        try:
            label_text = ""
            element_id = textarea.get_attribute("id") or ""
            if element_id:
                label = page.locator(f'label[for="{element_id}"]')
                if label.count():
                    label_text = label.first.inner_text(timeout=1000) or ""
            if not label_text:
                label_text = textarea.get_attribute("aria-label") or ""
            if not label_text:
                label_text = textarea.get_attribute("placeholder") or ""

            lower_label = label_text.lower()
            for item in answers:
                question = item["question"].lower()
                if question in lower_label or lower_label in question or _keyword_overlap(question, lower_label):
                    textarea.fill(item["answer"], timeout=3000)
                    filled.append(label_text or f"textarea_{index}")
                    break
        except Exception:
            continue
    return filled


def _keyword_overlap(a: str, b: str) -> bool:
    words_a = {word for word in re.split(r"\W+", a) if len(word) > 3}
    words_b = {word for word in re.split(r"\W+", b) if len(word) > 3}
    return bool(words_a & words_b)


def _upload_resume(page, resume_path: Path) -> bool:
    selectors = [
        'input[type="file"]#resume',
        'input[type="file"][name*="resume"]',
        'input[type="file"]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.set_input_files(str(resume_path), timeout=5000)
            return True
        except Exception:
            continue
    return False


def _click_submit(page) -> bool:
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")',
        'button:has-text("Submit")',
        '#btn-submit',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            page.wait_for_timeout(2000)
            return True
        except Exception:
            continue
    return False


def _fill_greenhouse(page, payload: ApplyFillPayload, resume_path: Path | None) -> list[str]:
    fields = payload.fields
    filled: list[str] = []

    mapping = [
        (["#first_name", 'input[name*="first_name"]'], fields.get("first_name", ""), "first_name"),
        (["#last_name", 'input[name*="last_name"]'], fields.get("last_name", ""), "last_name"),
        (["#email", 'input[type="email"]', 'input[name*="email"]'], fields.get("email", ""), "email"),
        (["#phone", 'input[type="tel"]', 'input[name*="phone"]'], fields.get("phone", ""), "phone"),
        (["#job_application_location", 'input[name*="location"]', "#candidate-location"], fields.get("location", ""), "location"),
        (['input[name*="linkedin"]', 'input[id*="linkedin"]'], fields.get("linkedin_url", ""), "linkedin"),
        (['input[name*="website"]', 'input[id*="website"]'], fields.get("website", ""), "website"),
    ]
    for selectors, value, label in mapping:
        if _set_input(page, selectors, value):
            filled.append(label)

    cover = fields.get("cover_letter", "")
    if cover:
        if _set_input(page, ['textarea[name*="cover"]', "#cover_letter"], cover):
            filled.append("cover_letter")

    answer_dicts = [{"question": item.question, "answer": item.answer} for item in payload.answers]
    filled.extend(_fill_textareas_by_keywords(page, answer_dicts))

    if resume_path and _upload_resume(page, resume_path):
        filled.append("resume")

    return filled


def _fill_lever(page, payload: ApplyFillPayload, resume_path: Path | None) -> list[str]:
    fields = payload.fields
    filled: list[str] = []

    mapping = [
        (['input[name="name"]', "#name", 'input[placeholder*="name" i]'], fields.get("full_name", ""), "name"),
        (['input[name="email"]', 'input[type="email"]'], fields.get("email", ""), "email"),
        (['input[name="phone"]', 'input[type="tel"]'], fields.get("phone", ""), "phone"),
        (['input[name="org"]', 'input[name="company"]'], fields.get("location", ""), "location"),
        (['input[name="urls[LinkedIn]"]', 'input[name*="linkedin" i]'], fields.get("linkedin_url", ""), "linkedin"),
    ]
    for selectors, value, label in mapping:
        if _set_input(page, selectors, value):
            filled.append(label)

    cover = fields.get("cover_letter", "")
    if cover:
        if _set_input(page, ['textarea[name="comments"]', "textarea"], cover):
            filled.append("cover_letter")

    answer_dicts = [{"question": item.question, "answer": item.answer} for item in payload.answers]
    filled.extend(_fill_textareas_by_keywords(page, answer_dicts))

    if resume_path and _upload_resume(page, resume_path):
        filled.append("resume")

    return filled


def run_apply_automation(
    job: Job,
    profile: SearchProfile,
    *,
    submit: bool,
    headless: bool = True,
) -> AutomationResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return AutomationResult(
            success=False,
            status="failed",
            message="Playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    payload = build_fill_payload(job, profile)
    if payload.ats_type not in SUPPORTED_AUTO_ATS:
        return AutomationResult(
            success=False,
            status="failed",
            message=f"Auto-apply is not supported for {payload.ats_type}. Use browser assist or manual apply.",
        )

    resume_path = None
    if payload.resume_filename:
        candidate = RESUMES_DIR / payload.resume_filename
        if candidate.exists():
            resume_path = candidate

    if not payload.fields.get("email"):
        return AutomationResult(
            success=False,
            status="failed",
            message="Add your email in Apply profile before auto-apply.",
        )

    screenshot_path = SCREENSHOTS_DIR / f"job_{job.id}_{'submit' if submit else 'fill'}.png"
    keep_browser_open = not submit
    visible_browser = keep_browser_open or not headless

    cdp_url = (settings.chrome_cdp_url or "").strip()
    use_cdp = bool(cdp_url)

    playwright = sync_playwright().start()
    # owns_browser: True only when we launched Chromium ourselves. In CDP mode we
    # attach to the user's real Chrome and must never close it or their tabs.
    owns_browser = False
    if use_cdp:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            playwright.stop()
            return AutomationResult(
                success=False,
                status="failed",
                message=(
                    f"Could not connect to Chrome at {cdp_url}. Make sure Chrome is "
                    f"running with remote debugging enabled. ({exc})"
                ),
            )
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
    else:
        browser = playwright.chromium.launch(headless=not visible_browser)
        owns_browser = True
        page = browser.new_page()
    try:
        page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)

        if payload.ats_type == "greenhouse":
            filled = _fill_greenhouse(page, payload, resume_path)
        else:
            filled = _fill_lever(page, payload, resume_path)

        if not filled:
            return AutomationResult(
                success=False,
                status="failed",
                message="Opened the posting but could not find application fields to fill.",
            )

        page.screenshot(path=str(screenshot_path), full_page=True)
        submitted = False

        if submit:
            submitted = _click_submit(page)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(screenshot_path), full_page=True)
            if not submitted:
                return AutomationResult(
                    success=True,
                    status="filled",
                    message="Form filled but submit button was not found. Review the browser screenshot and submit manually.",
                    filled_fields=filled,
                    submitted=False,
                    screenshot_path=str(screenshot_path),
                )

        status = "submitted" if submitted else "filled"
        message = (
            "Application submitted automatically."
            if submitted
            else "Application form filled in a browser window left open for your review. Submit manually when ready."
        )
        return AutomationResult(
            success=True,
            status=status,
            message=message,
            filled_fields=filled,
            submitted=submitted,
            screenshot_path=str(screenshot_path),
        )
    except Exception as exc:
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = None
        return AutomationResult(
            success=False,
            status="failed",
            message=f"Auto-apply failed: {exc}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )
    finally:
        if owns_browser:
            # We launched this Chromium ourselves; close it unless the user
            # asked to keep it open to review the filled form.
            if not keep_browser_open:
                browser.close()
                playwright.stop()
        else:
            # CDP mode: never close the user's real Chrome or the new tab.
            # Just disconnect our Playwright client — the filled tab stays open.
            playwright.stop()
