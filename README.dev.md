# Career Agent — Developer Guide

Local job-search agent: FastAPI backend + vanilla-JS single-page frontend + SQLite. AI (OpenAI) digests resumes and powers the chat agent; Playwright drives a real Chrome for auto-apply.

## Stack & layout

- **Backend:** FastAPI (`backend/app`), SQLAlchemy + SQLite (`data/jobs.db`).
- **Frontend:** static SPA in `backend/static` (`index.html`, `assets/app.js`, `assets/styles.css`) — no build step.
- **AI:** OpenAI Chat Completions.
- **Browser automation:** Playwright (sync) over CDP.

```
backend/app/
  main.py           # app + lifespan (runs schema migrations, seeds companies)
  routes.py         # all HTTP endpoints (user-scoped via X-User-Id)
  models.py         # User, Job, JobEvent, ApplyAttempt, SearchProfile, TargetCompany
  config.py         # env-backed settings (reloaded per request)
  schemas*.py       # Pydantic models
  services/
    deps.py             # get_current_user (X-User-Id header)
    users.py            # profile CRUD
    profile.py          # per-user SearchProfile
    profile_extractor.py / apply_profile_extractor.py   # resume digest (strong model)
    search_agent.py     # Adzuna search + upsert (canonical dedup)
    company_search.py   # Greenhouse/Lever/Workday board search
    profile_match.py    # job_match_score + strictness_to_threshold
    url_canonical.py    # canonical_job_url (dedup key)
    chat_agent.py       # unified chat brain
    nl_job_agent.py     # NL -> plan (list/ignore/delete/update/search/company_search)
    apply_service.py    # apply orchestration
    apply_automation.py # Playwright fill for Greenhouse/Lever
    agentic_apply.py    # follow-redirects + generic fill (any ATS) over CDP
    *_schema.py         # idempotent startup migrations
```

## Running

```powershell
.\start.ps1     # creates .venv, installs requirements + Playwright Chromium, runs uvicorn on :8000
```

Direct (dev): `uvicorn app.main:app --app-dir backend --reload --port 8000`. Migrations run on startup (lifespan) and are idempotent.

## Configuration (`backend/.env`, see `.env.example`)

| Var | Purpose |
|---|---|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Adzuna job-search API |
| `ADZUNA_COUNTRY` | default `us` |
| `OPENAI_API_KEY` | enables AI (falls back to heuristics if unset) |
| `OPENAI_MODEL` | general agentic work (chat, fit, materials, summaries) — cheap/fast (`gpt-4o-mini`) |
| `OPENAI_DIGEST_MODEL` | **resume digestion only** (once per upload) — a stronger model (`gpt-5.2`) |
| `CHROME_CDP_URL` | real-Chrome CDP endpoint for auto-apply (e.g. `http://127.0.0.1:9333`); blank = launch throwaway Chromium |
| `SEARCH_TITLES/KEYWORDS/LOCATIONS` | defaults used before a profile exists |

`config.Settings` reloads `.env` on each access, so most changes take effect without a restart (code changes still need one).

## Multi-user (named profiles)

- Every data row (`Job`, `SearchProfile`, `TargetCompany`) has a `user_id`; all queries filter by it.
- The active profile is passed as the **`X-User-Id`** header (frontend stores it in `localStorage`); `get_current_user` resolves it. User CRUD endpoints don't require the header.
- Resume files are namespaced per user (`{user_id}__{filename}` in `data/resumes/`).
- Migration (`user_schema.ensure_user_schema`) adds `user_id`, creates a **Default** profile, and backfills existing rows.

## Resume digest & match strictness

- On upload, `profile_extractor` / `apply_profile_extractor` call `OPENAI_DIGEST_MODEL` to produce search criteria; results are saved to the profile and reused for subsequent searches (the strong model runs only at upload time).
- `match_strictness` (1–10) on `SearchProfile` maps to a score threshold via `strictness_to_threshold` (`s*8` → 8…80).
- `job_match_score` (0–100) = executive-title/seniority match (55) + keyword/skill/industry overlap (each hit +15, capped 45); hard-excluded terms → 0. Both `run_job_search` and `run_company_search` drop jobs scoring below the threshold.

## De-duplication

Aggregators (Adzuna) append per-request tokens (`se`, `v`, …) so the same posting arrives with a different URL each search. `url_canonical.canonical_job_url` strips tracking params; `Job.canonical_url` is the dedup key (per user). `job_schema.ensure_job_dedup_schema` backfills it and collapses pre-existing duplicates.

## Apply paths

| Path | ATS support | Submits? | Mechanism |
|---|---|---|---|
| **Manual** | any | you do | `Prepare to apply` builds a kit (cover letter, answers) to copy |
| **Agentic apply** | **any** (SmartRecruiters, Workday, Greenhouse, Lever, custom) | never | `agentic_apply.py` drives real Chrome over CDP, follows redirects to the form, maps fields (heuristics + OpenAI fallback), uploads resume, stops at login/CAPTCHA |
| **Playwright auto-fill** | Greenhouse, Lever only | optional | `apply_automation.py` fills known selectors; can auto-submit with settings + confidence |
| **Chrome extension** | Greenhouse, Lever | you do | `extension/` in-browser fill |

### Real Chrome for auto-apply

Auto-apply drives your actual Chrome so it reuses logged-in sessions. Two **separate** Chrome debugging mechanisms exist:

- **Classic remote debugging (port 9333)** — started by `start-chrome-debug.ps1` with a dedicated profile. This is what Playwright/agentic-apply attaches to (`CHROME_CDP_URL`). Serves `/json/version`.
- **`chrome-devtools-mcp` "Remote debugging" toggle (port 9222)** — a *secured* endpoint that only that MCP can attach to (no `/json` endpoints, WS handshake). **Playwright cannot use it** — hence the separate classic-debug Chrome on 9333.

Agentic apply follows up to 6 hops through aggregator/redirect pages to reach the real form, waits out delayed JS redirects, and only fills a page it recognizes as an application form (not an aggregator's search/newsletter box). Screenshots land in `data/apply_screenshots/`.

## API

All data endpoints require the **`X-User-Id`** header.

Profiles: `GET/POST /api/users`, `DELETE /api/users/{id}`
Chat: `POST /api/agent/chat`
Jobs: `GET /api/jobs`, `POST /api/jobs`, `POST /api/jobs/{id}/status`, `POST /api/jobs/{id}/fit`, `POST /api/jobs/{id}/description/enrich`, `DELETE /api/jobs/{id}`, `DELETE /api/jobs`
Apply: `GET /api/jobs/{id}/apply`, `POST .../apply/prepare`, `POST .../apply/assist`, `POST .../apply/auto` (Greenhouse/Lever), `POST .../apply/agentic` (any ATS), `POST .../apply/complete`, `GET .../apply/screenshot`, `GET /api/apply/match?url=`
Profile: `GET/PUT /api/profile`, `GET/PUT /api/profile/apply`, `POST/DELETE /api/profile/resume`
Search: `POST /api/agent/search`, `POST /api/agent/company-search`, `POST /api/agent/nl-jobs/plan`, `POST /api/agent/nl-jobs/execute`
Companies: `GET/POST /api/companies`, `PATCH/DELETE /api/companies/{id}`
Misc: `GET /api/dashboard`, `GET /api/health`

## Notes & limitations

- **LinkedIn/Indeed** job listings are not imported (no open API; scraping violates ToS). Add such jobs manually by URL.
- **Workday** board search returns titles without full descriptions, so keyword scoring there is title-only.
- Auto-apply is best-effort on arbitrary sites; logins, CAPTCHAs, and unusual widgets cause it to stop and hand off.
- Secrets live only in `backend/.env` (gitignored). Never commit it.
