# Career Agent

**Drop in your resume. Get matched to jobs. Apply and track — all in one place.**

Career Agent reads your resume, finds roles that fit, helps you apply, and keeps your whole pipeline organized. Works for any role, any industry — it tailors the search to *you*.

## What it does

- **Chat-first UI** — a ChatGPT-style interface: tell the agent to "search jobs from my resume", "search company X", or "ignore jobs that aren't senior", and it does it (destructive actions ask to confirm).
- **Named profiles (multi-user)** — Netflix-style profiles, each with its own resume, jobs, target companies, and settings. No passwords.
- **Resume digest** — on upload, AI turns your resume into tailored search criteria (titles, keywords, skills, industries, exclusions). Uses a stronger model for this one-time step (configurable).
- **Match strictness (1–10)** — a dial that controls how closely jobs must match your resume before they're added (1 = more jobs, 10 = only the best).
- **Search agent** — finds matching roles from job boards (Adzuna) and company career pages (Greenhouse, Lever, Workday); de-duplicates by canonical URL so the same posting is never added twice.
- **Jobs view** — clean list with per-row **Auto-fill** and **Ignore**; click any job for a detail modal (fit, apply, status, notes).
- Tracks status: new, reviewing, applied, interview, offer, rejected, passed, withdrawn; stores everything in a local SQLite DB (`data/jobs.db`).
- **Agentic apply** — drives your real Chrome to follow a posting link through redirects to the actual application form and fill it from your profile (any ATS), stopping before submit and at logins/CAPTCHAs.
- **Chrome extension (optional)** — in-browser fill on Greenhouse and Lever.
- **Playwright auto-fill (Greenhouse/Lever)** — deterministic fill/optional auto-submit for those two ATS.

## Quick start

1. Open PowerShell in `I:\jobsearch`
2. Start the app (creates venv, installs dependencies, and Playwright Chromium):

```powershell
.\start.ps1
```

3. Optional: configure job search API keys

```powershell
Copy-Item .env.example .env
```

Get free Adzuna keys from [https://developer.adzuna.com/](https://developer.adzuna.com/) and set:

```
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
```

Optional: enable AI resume analysis (highly recommended):

```
OPENAI_API_KEY=your_openai_key
# General agentic work (chat, fit, materials, summaries) — cheap/fast
OPENAI_MODEL=gpt-4o-mini
# Resume digestion only (run once per resume upload) — a stronger model
OPENAI_DIGEST_MODEL=gpt-5.2
```

Without OpenAI, resume upload still works using basic keyword extraction.

4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and pick or create a profile.

### Profiles (multi-user)

On first load you'll see a "Who's searching?" picker. Create a profile (just a name — no password) or pick an existing one. Each profile keeps its own resume, jobs, target companies, and settings, fully isolated. Switch or add profiles anytime from the top-bar profile menu.

## Apply workflows

### Manual apply (default)

1. Select a job → **Analyze fit** → **Prepare to apply**
2. Open the posting, copy materials from the apply kit, submit on the company site
3. Click **I submitted — mark applied**

### Agentic apply (any ATS — recommended)

Drives your **real Chrome** to follow a posting link through redirects/aggregators to the actual application form and fill it from your profile — works on any ATS (SmartRecruiters, Workday, Greenhouse, Lever, custom). It **never submits**, stops at logins/CAPTCHAs, and leaves the tab open for your review.

1. Start the debug Chrome (classic remote debugging on port 9333, separate from normal Chrome):

   ```powershell
   .\start-chrome-debug.ps1
   ```

2. Set `CHROME_CDP_URL=http://127.0.0.1:9333` in `backend/.env` (default). First time, log into any job sites in that Chrome window.
3. In the Jobs view click **Auto-fill** on any job (or **Agentic apply** in the job modal). Review the filled form in Chrome and submit yourself.

> Field mapping uses keyword heuristics plus an OpenAI fallback; the resume is uploaded to the form when the site supports it.

### Phase 2: Chrome extension (browser assist)

See [extension/README.md](extension/README.md) for full install steps.

1. Load unpacked extension from `extension/` in `chrome://extensions`
2. In Career Agent, click **Browser assist fill** on a Greenhouse or Lever job
3. On the posting, click **Fill from Career Agent**
4. Review and submit manually

### Phase 3: Playwright (local auto-fill)

Requires Chromium installed by `start.ps1` (`playwright install chromium`).

1. Complete your **Apply profile** (email required)
2. On a Greenhouse or Lever job with sufficient confidence:
   - **Auto-fill form (no submit)** — opens a visible browser, fills fields, leaves the window open for review
   - **Auto-apply (submit)** — fills and submits (enable in Apply profile + meet minimum confidence)

Screenshots are saved under `data/apply_screenshots/` and viewable at `/api/jobs/{id}/apply/screenshot`.

#### Apply in your real Google Chrome (optional)

By default Playwright launches a throwaway Chromium. To auto-apply in your **own Chrome**
instead — reusing your logged-in sessions (LinkedIn, Greenhouse, Lever) — run it with
classic remote debugging and point the app at it:

1. Start the debug Chrome (dedicated profile on port 9333, separate from your normal Chrome):

   ```powershell
   .\start-chrome-debug.ps1
   ```

2. Set `CHROME_CDP_URL=http://127.0.0.1:9333` in `backend/.env` (already set by default).
3. The first time, log into any job sites in that Chrome window; logins persist in its profile.
4. Use **Auto-fill** / **Auto-apply** as usual — the form opens in that real Chrome as a new tab,
   which is left open for you. The app never closes your browser.

Leave `CHROME_CDP_URL` blank to fall back to the throwaway-Chromium behavior.

> Note: this classic-debug Chrome is **separate** from the `chrome-devtools-mcp` "Remote debugging"
> toggle (port 9222). That toggle is a secured endpoint only the MCP can attach to; Playwright needs
> the classic protocol this script starts.

## Which ATS types support auto-apply?

Career Agent classifies each job from the **URL stored on the job record** (not where you eventually applied in the browser).

| ATS | Example URL | Browser extension (Phase 2) | Playwright auto-fill (Phase 3) | Auto-submit |
|-----|-------------|----------------------------|--------------------------------|-------------|
| **Greenhouse** | `boards.greenhouse.io/...` | Yes | Yes | Yes (with settings) |
| **Lever** | `jobs.lever.co/...` | Yes | Yes | Yes (with settings) |
| **Workday** | `*.wd5.myworkdayjobs.com/...` | No | No | No |
| **LinkedIn / Indeed** | `linkedin.com/jobs/...` | No | No | No |
| **Adzuna aggregator** | `adzuna.com/...` | No | No | No |
| **Other / unknown** | Company custom sites | No | No | No |

Workday (used by HP, Intel, NVIDIA, and many large employers) is **manual apply only** for now. Workday forms often require login, long custom question sets, and heavy JavaScript — automation is unreliable compared to Greenhouse and Lever.

### Why auto-apply may be missing (even with a saved Apply profile)

Auto-apply is **not** blocked by saving your profile alone. It is blocked when:

1. **The stored job URL is not Greenhouse or Lever** — jobs imported from Adzuna usually link to an aggregator or redirect, not the company ATS.
2. **The job is Workday** — detected from `myworkdayjobs.com` URLs; manual apply with the apply kit is the supported path.
3. **The URL is a careers home page, not a job posting** — e.g. `.../userHome` will not work; use the direct requisition link (`/job/...`).
4. **Apply profile is missing email** — required for Playwright fill.

Saving name, email, and other Apply profile fields is necessary but not sufficient if the job URL points to the wrong ATS.

### Example: HP role applied on Workday

You might have a pipeline entry like:

- **Title:** Vice President, CTO Operations  
- **Company:** HP Inc.  
- **Source:** adzuna  
- **Applied manually at:** `https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/...`

In that case auto-apply would not appear because:

- The tracker job likely still has an **Adzuna URL** (classified as unsupported), and/or
- HP’s application site is **Workday**, which is outside Phase 2 and Phase 3 support.

**Recommended workflow for Workday roles:**

1. Find the real Workday job posting URL (not Adzuna, not the careers home page).
2. Update the job in Career Agent with that URL (optional, improves ATS detection and description fetch).
3. **Prepare to apply** — generate cover letter and tailored answers.
4. Apply manually on the company site.
5. Click **I submitted — mark applied**.

### Adzuna and target-company search

- **Adzuna search** imports jobs with Adzuna links. Use **Open posting**, find the company’s real application page, and optionally **edit the job URL** to the Greenhouse, Lever, or Workday posting if you want correct ATS detection.
- **Target company search** can import from Greenhouse, Lever, and Workday career pages directly; Greenhouse and Lever imports are the best candidates for browser assist and auto-fill.

## Usage

- **Upload resume**: AI extracts titles, keywords, skills, locations, and exclusions
- **Edit search profile**: tweak any field and click Save profile
- **Run job search**: uses your saved criteria and imports new jobs from Adzuna
- **Search target companies**: fetches roles from Greenhouse, Lever, and Workday career pages
- **Add job manually**: paste a posting URL from any company site or LinkedIn
- **Open Google Jobs**: quick external search helper
- **Pipeline view**: filter jobs, update status, save notes, view timeline
- **Dashboard**: counts by status and recent activity

## Notes

- Auto-submit only runs when enabled in Apply profile, confidence meets your threshold, and the job URL is Greenhouse or Lever.
- Phase 2 (extension) and Phase 3 (Playwright) support **Greenhouse and Lever only**. Workday, LinkedIn, Indeed, Adzuna links, and custom sites use **manual apply** with the apply kit.
- The apply panel shows specific reasons per job (ATS type, missing description, profile gaps).
- Use **Mark applied** after you submit an application.
- Without Adzuna keys, manual tracking still works fully.

## API

All data endpoints are scoped to the active profile via an **`X-User-Id`** request header.

- `GET /api/users` · `POST /api/users` · `DELETE /api/users/{id}` — profiles
- `POST /api/agent/chat` — chat brain (search / company-search / filter / ignore)
- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/{id}/status`
- `POST /api/jobs/{id}/fit`
- `POST /api/jobs/{id}/description/enrich`
- `GET /api/jobs/{id}/apply`
- `POST /api/jobs/{id}/apply/prepare`
- `POST /api/jobs/{id}/apply/assist`
- `POST /api/jobs/{id}/apply/auto` — Greenhouse/Lever Playwright fill
- `POST /api/jobs/{id}/apply/agentic` — agentic apply (any ATS, real Chrome)
- `POST /api/jobs/{id}/apply/complete`
- `GET /api/jobs/{id}/apply/screenshot`
- `GET /api/apply/match?url=`
- `GET/PUT /api/profile/apply`
- `GET /api/profile`
- `PUT /api/profile`
- `POST /api/profile/resume`
- `DELETE /api/profile/resume`
- `POST /api/agent/search`
- `GET /api/companies`
- `POST /api/companies`
- `PATCH /api/companies/{id}`
- `DELETE /api/companies/{id}`
- `POST /api/agent/company-search`
- `GET /api/dashboard`
