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

"""Agentic apply: drive the user's real Chrome to follow a job link to the real
application form and fill it from the user's profile — fill-only, never submit.

Works on any ATS (unlike the Greenhouse/Lever-only apply_automation), by
following redirect/aggregator hops to the actual form, reading the live fields,
mapping them to the user's data with keyword heuristics plus an OpenAI fallback,
and stopping at logins/CAPTCHAs or before any submit/next control.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..config import settings
from ..schemas_apply import ApplyFillPayload
from .apply_automation import SCREENSHOTS_DIR

MAX_HOPS = 6

APPLY_TEXT = re.compile(
    r"(apply for this job|apply now|i'?m interested|start application|easy apply|\bapply\b)",
    re.I,
)
COOKIE_TEXT = re.compile(r"(accept all|accept|i agree|agree|decline|reject all|reject)", re.I)
SUBMIT_TEXT = re.compile(r"(submit|send application|next|continue|review)", re.I)
CAPTCHA_SEL = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[title*='captcha' i]"

# Known real ATS hosts — an email field on these is almost certainly the app form.
ATS_HOSTS = (
    "greenhouse.io", "lever.co", "smartrecruiters.com", "myworkdayjobs.com",
    "icims.com", "ashbyhq.com", "workable.com", "bamboohr.com", "jobvite.com",
    "taleo.net", "successfactors", "oraclecloud.com", "eightfold.ai", "paylocity.com",
    "dayforcehcm.com", "phenom", "avature.net",
)
# Aggregators / boards that are never the real application form — keep following.
AGGREGATOR_HOSTS = (
    "adzuna.", "indeed.", "linkedin.", "glassdoor.", "ziprecruiter.", "dejobs.org",
    "jobsyn.org", "google.com", "simplyhired.", "monster.",
)
NAME_SEL = (
    "input[name*='name' i]:not([name*='company' i]):not([name*='user' i]), "
    "input[id*='name' i]:not([id*='company' i]):not([id*='user' i]), "
    "input[autocomplete='given-name'], input[autocomplete='family-name'], input[autocomplete='name']"
)

# label keyword -> payload.fields key (order matters; first match wins)
FIELD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"first name|given name|forename", re.I), "first_name"),
    (re.compile(r"last name|surname|family name", re.I), "last_name"),
    (re.compile(r"full name|your name|^name$|legal name", re.I), "full_name"),
    (re.compile(r"e-?mail", re.I), "email"),  # also covers "confirm email"
    (re.compile(r"phone|mobile|\btel\b", re.I), "phone"),
    (re.compile(r"linkedin", re.I), "linkedin_url"),
    (re.compile(r"portfolio|website|personal site|\burl\b", re.I), "website"),
    (re.compile(r"city|location|town", re.I), "location"),
    (re.compile(r"work authorization|authorized to work|eligibility", re.I), "work_authorization"),
    (re.compile(r"sponsor|visa", re.I), "requires_sponsorship"),
    (re.compile(r"cover letter", re.I), "cover_letter"),
    (re.compile(r"message|why|interest|comments|additional info", re.I), "cover_letter"),
]


@dataclass
class AgenticResult:
    success: bool
    status: str
    message: str
    final_url: str | None = None
    filled_fields: list[str] = field(default_factory=list)
    unmapped_fields: list[str] = field(default_factory=list)
    blocker: str | None = None  # login | captcha | no_form
    has_next: bool = False
    screenshot_path: str | None = None


# ------------------------------------------------------------------ helpers ---
def _connect_real_chrome(playwright):
    """Attach to the user's running Chrome over CDP. Returns (browser, page)."""
    browser = playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    return browser, context, page


def _visible(el) -> bool:
    try:
        return el.is_visible()
    except Exception:
        return False


def _text_of(el) -> str:
    try:
        t = (el.inner_text() or "").strip()
        if t:
            return t
        t = (el.text_content() or "").strip()
        if t:
            return t
        return (el.get_attribute("value") or "").strip()
    except Exception:
        return ""


def _clean_value(value: str, multiline: bool) -> str:
    v = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", " ")
    v = v.replace("\\", "")  # some ATS reject stray backslashes
    if not multiline:
        v = re.sub(r"\s+", " ", v).strip()
    return v


def _dismiss_cookies(page) -> None:
    try:
        for el in page.query_selector_all("button, a"):
            if not _visible(el):
                continue
            if COOKIE_TEXT.fullmatch(_text_of(el)) or (
                COOKIE_TEXT.search(_text_of(el)) and "cookie" in (page.title() or "").lower()
            ):
                try:
                    el.click(timeout=1500)
                    page.wait_for_timeout(400)
                    return
                except Exception:
                    continue
    except Exception:
        pass


REDIRECTOR_MARKERS = ("/land/ad", "jobsyn.org", "aztt=", "/redirect", "outbound")


def _is_redirector(url: str) -> bool:
    return any(m in url for m in REDIRECTOR_MARKERS)


def _settle(page) -> None:
    """Wait out HTTP + delayed JS/meta redirects until the DOM is stable.

    Requires the URL to be queryable (not mid-navigation) and unchanged across
    two consecutive checks, and never settles on a known redirector URL.
    """
    last = None
    stable = 0
    for _ in range(22):  # ~ up to 15s
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        try:
            cur = page.url
            page.query_selector("a")  # throws while a navigation is in flight
            ready = True
        except Exception:
            cur, ready = None, False

        if ready and cur and not _is_redirector(cur) and cur == last:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        last = cur
        page.wait_for_timeout(700)


def _host(page) -> str:
    try:
        return urlparse(page.url).netloc.lower()
    except Exception:
        return ""


def _has_application_form(page) -> bool:
    """True only for a real application form — not aggregator search/newsletter boxes."""
    try:
        host = _host(page)
        if any(agg in host for agg in AGGREGATOR_HOSTS):
            return False  # aggregator page: its inputs are search/alert boxes, keep going

        email = page.query_selector(
            "input[type='email'], input[name*='email' i], input[id*='email' i]"
        )
        if not email or not _visible(email):
            return False

        on_ats = any(h in host for h in ATS_HOSTS)
        has_name = any(_visible(el) for el in page.query_selector_all(NAME_SEL))
        has_file = any(_visible(el) for el in page.query_selector_all("input[type='file']"))
        # Real form = email plus a name field or resume upload, or a known ATS host.
        return on_ats or has_name or has_file
    except Exception:
        return False


def _find_apply_control(page):
    try:
        for el in page.query_selector_all("a, button, input[type='button'], input[type='submit']"):
            if not _visible(el):
                continue
            txt = _text_of(el)
            if not txt or len(txt) > 40:
                continue
            if "filter" in txt.lower():
                continue
            if APPLY_TEXT.search(txt):
                return el
    except Exception:
        pass
    return None


def _detect_blocker(page) -> str | None:
    try:
        if page.query_selector(CAPTCHA_SEL):
            return "captcha"
        pw = page.query_selector("input[type='password']")
        if pw and _visible(pw):
            return "login"
    except Exception:
        pass
    return None


def _label_for(page, el) -> str:
    for attr in ("aria-label",):
        val = el.get_attribute(attr)
        if val:
            return val.strip()
    el_id = el.get_attribute("id")
    if el_id:
        try:
            lab = page.query_selector(f'label[for="{el_id}"]')
            if lab:
                t = (lab.inner_text() or "").strip()
                if t:
                    return t
        except Exception:
            pass
    # wrapping label
    try:
        t = el.evaluate("e => { const l = e.closest('label'); return l ? l.innerText : ''; }")
        if t and t.strip():
            return t.strip()
    except Exception:
        pass
    return (el.get_attribute("placeholder") or el.get_attribute("name") or "").strip()


def _map_label_to_value(label: str, payload: ApplyFillPayload) -> str | None:
    fields = payload.fields
    for pattern, key in FIELD_RULES:
        if pattern.search(label):
            value = fields.get(key, "")
            if not value:
                return None
            # Don't fill URL fields with non-URL junk (e.g. a literal "Linkedin").
            if key in ("linkedin_url", "website") and "." not in value:
                return None
            return value
    return None


def _answer_for_label(label: str, payload: ApplyFillPayload) -> str | None:
    low = label.lower()
    words = {w for w in re.split(r"\W+", low) if len(w) > 3}
    for item in payload.answers:
        q = item.question.lower()
        qwords = {w for w in re.split(r"\W+", q) if len(w) > 3}
        if q in low or low in q or (words & qwords):
            return item.answer or None
    return None


def _llm_fill_unmapped(labels: list[str], payload: ApplyFillPayload) -> dict[str, str]:
    if not labels or not settings.openai_api_key:
        return {}
    candidate = {k: v for k, v in payload.fields.items() if v}
    candidate["answers"] = [{"q": a.question, "a": a.answer} for a in payload.answers]
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        prompt = (
            "You fill a job application form for a candidate. Given the candidate data "
            "and a list of form field labels, return a JSON object mapping each label to "
            "the best value from the candidate data, or an empty string if unknown. "
            "Do not invent facts. Keep answers concise.\n\n"
            f"CANDIDATE:\n{json.dumps(candidate)[:4000]}\n\n"
            f"FIELD LABELS:\n{json.dumps(labels)}\n\n"
            'Return only JSON like {"Label": "value"}.'
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
    except Exception:
        return {}


def _is_autocomplete(el) -> bool:
    for attr in ("role", "aria-autocomplete", "aria-haspopup"):
        val = (el.get_attribute(attr) or "").lower()
        if val in ("combobox", "listbox", "list", "both"):
            return True
    return False


def _fill_text(page, el, value: str, autocomplete: bool, multiline: bool = False) -> bool:
    """Fill a field and verify the value actually persisted (autocomplete/validated
    fields often clear themselves, so a fill that 'succeeds' may not stick)."""
    value = _clean_value(value, multiline)
    if not value:
        return False
    try:
        el.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        el.click(timeout=2000)
    except Exception:
        pass
    try:
        el.fill("", timeout=1500)
    except Exception:
        pass
    try:
        el.fill(value, timeout=3000)
    except Exception:
        try:
            el.type(value, delay=15, timeout=3000)
        except Exception:
            return False

    if autocomplete:
        page.wait_for_timeout(1300)  # let async suggestions load
        try:
            el.press("ArrowDown")
            page.wait_for_timeout(350)
            el.press("Enter")
            page.wait_for_timeout(300)
        except Exception:
            pass

    try:
        current = (el.input_value(timeout=1500) or "").strip()
        return bool(current)
    except Exception:
        return True


def _fill_select(el, value: str) -> bool:
    try:
        el.select_option(label=value)
        return True
    except Exception:
        try:
            el.select_option(value=value)
            return True
        except Exception:
            return False


# --------------------------------------------------------------- main entry ---
def run_agentic_apply(payload: ApplyFillPayload, resume_path: Path | None) -> AgenticResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return AgenticResult(False, "failed", "Playwright is not installed.")

    if not (settings.chrome_cdp_url or "").strip():
        return AgenticResult(
            False, "failed",
            "Set CHROME_CDP_URL and start Chrome with .\\start-chrome-debug.ps1 to use agentic apply.",
        )
    if not payload.fields.get("email"):
        return AgenticResult(False, "failed", "Add your email in Apply profile first.")

    job_id = payload.job_id
    screenshot_path = SCREENSHOTS_DIR / f"job_{job_id}_agentic.png"

    playwright = sync_playwright().start()
    try:
        try:
            browser, context, page = _connect_real_chrome(playwright)
        except Exception as exc:
            return AgenticResult(
                False, "failed",
                f"Could not connect to Chrome at {settings.chrome_cdp_url}. Is it running with remote debugging? ({exc})",
            )

        # 1. Navigate + follow to the application form.
        try:
            page.goto(payload.job_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            return AgenticResult(False, "failed", f"Could not open the posting: {exc}")

        _settle(page)
        reached = False
        for _ in range(MAX_HOPS):
            _settle(page)
            _dismiss_cookies(page)

            blocker = _detect_blocker(page)
            if blocker:
                _safe_shot(page, screenshot_path)
                return AgenticResult(
                    False, "blocked",
                    f"Reached a {blocker} wall — finish this one manually in Chrome.",
                    final_url=page.url, blocker=blocker, screenshot_path=str(screenshot_path),
                )

            if _has_application_form(page):
                reached = True
                break

            control = _find_apply_control(page)
            if not control:
                break

            # Prefer navigating to an anchor's href directly — bypasses cookie
            # overlays and popup windows that would defeat a click.
            href = control.get_attribute("href")
            try:
                tag = control.evaluate("e => e.tagName.toLowerCase()")
            except Exception:
                tag = ""
            navigated = False
            if tag == "a" and href and href.startswith("http"):
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=30000)
                    navigated = True
                except Exception:
                    navigated = False
            if not navigated:
                before = len(context.pages)
                try:
                    control.click(timeout=5000)
                except Exception:
                    try:
                        control.evaluate("e => e.click()")
                    except Exception:
                        break
                page.wait_for_timeout(2000)
                if len(context.pages) > before:
                    page = context.pages[-1]
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass

        if not reached:
            _safe_shot(page, screenshot_path)
            return AgenticResult(
                False, "blocked",
                "Couldn't locate a fillable application form after following the links. "
                "Open it in Chrome and apply manually.",
                final_url=page.url, blocker="no_form", screenshot_path=str(screenshot_path),
            )

        # re-check for a login/captcha that appears with the form
        blocker = _detect_blocker(page)
        if blocker:
            _safe_shot(page, screenshot_path)
            return AgenticResult(
                False, "blocked", f"Reached a {blocker} wall — finish manually in Chrome.",
                final_url=page.url, blocker=blocker, screenshot_path=str(screenshot_path),
            )

        # 2. Collect + map + fill fields.
        filled: list[str] = []
        unmapped_labels: list[str] = []
        pending_llm: list[tuple[object, str, bool]] = []  # (el, label, autocomplete)
        resume_uploaded = False

        for el in page.query_selector_all("input, textarea, select"):
            try:
                if not _visible(el):
                    continue
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                itype = (el.get_attribute("type") or "text").lower()

                if tag == "input" and itype == "file":
                    if resume_path and not resume_uploaded:
                        try:
                            el.set_input_files(str(resume_path), timeout=5000)
                            filled.append("resume")
                            resume_uploaded = True
                        except Exception:
                            pass
                    continue
                if itype in ("hidden", "submit", "button", "reset", "image", "checkbox", "radio"):
                    continue
                if itype == "password":
                    continue  # never touch

                label = _label_for(page, el)
                if not label:
                    continue

                value = _map_label_to_value(label, payload)
                if value is None:
                    value = _answer_for_label(label, payload)

                if tag == "select":
                    if value and _fill_select(el, value):
                        filled.append(label)
                    continue

                multiline = tag == "textarea"
                if value:
                    if _fill_text(page, el, value, _is_autocomplete(el), multiline):
                        filled.append(label)
                    else:
                        unmapped_labels.append(label)
                else:
                    pending_llm.append((el, label, _is_autocomplete(el), multiline))
                    unmapped_labels.append(label)
            except Exception:
                continue

        # 3. AI fallback for unmapped labelled fields.
        if pending_llm:
            resolved = _llm_fill_unmapped([lbl for _, lbl, _, _ in pending_llm], payload)
            filled_labels = set()
            for el, label, auto, multiline in pending_llm:
                val = resolved.get(label)
                if val and _fill_text(page, el, val, auto, multiline):
                    filled.append(label + " (AI)")
                    filled_labels.add(label)
            unmapped_labels = [lbl for lbl in unmapped_labels if lbl not in filled_labels]

        unmapped_labels = list(dict.fromkeys(unmapped_labels))

        # 4. Detect a submit/next control but DO NOT click it.
        has_next = False
        for el in page.query_selector_all("button, input[type='submit'], a"):
            if _visible(el) and SUBMIT_TEXT.search(_text_of(el)):
                has_next = True
                break

        _safe_shot(page, screenshot_path)

        if not filled:
            return AgenticResult(
                False, "blocked",
                "Found the form but couldn't map any fields — apply manually in Chrome.",
                final_url=page.url, unmapped_fields=unmapped_labels,
                has_next=has_next, screenshot_path=str(screenshot_path),
            )

        msg = f"Filled {len(filled)} field(s) in Chrome. Review and submit yourself."
        if has_next:
            msg = f"Filled page 1 ({len(filled)} field(s)). Review and click Next/Submit in Chrome."
        if unmapped_labels:
            msg += f" Left {len(unmapped_labels)} field(s) for you."
        return AgenticResult(
            True, "filled", msg, final_url=page.url, filled_fields=filled,
            unmapped_fields=unmapped_labels, has_next=has_next,
            screenshot_path=str(screenshot_path),
        )
    except Exception as exc:
        return AgenticResult(False, "failed", f"Agentic apply failed: {exc}")
    finally:
        # Never close the user's real Chrome or the filled tab; just disconnect.
        try:
            playwright.stop()
        except Exception:
            pass


def _safe_shot(page, path: Path) -> None:
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        pass
