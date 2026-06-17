# Career Agent

Personal MVP for tracking VP / Senior Director semiconductor job search.

## What it does

- Upload your resume to generate tailored job search criteria with AI
- Edit and save search profile (titles, keywords, skills, locations, exclusions)
- Runs a search agent for executive semiconductor roles using your profile
- Scans target company career pages (Greenhouse, Lever, and Workday)
- Pre-seeds semiconductor target companies (Waymo, Tenstorrent, NVIDIA, Intel, etc.)
- Stores jobs in a local SQLite database (`data/jobs.db`)
- Tracks status: new, reviewing, applied, interview, offer, rejected, passed, withdrawn
- Provides a web UI for pipeline management, notes, and timeline history
- **Phase 2:** Chrome extension for in-browser fill on Greenhouse and Lever
- **Phase 3:** Playwright auto-fill and optional auto-submit locally

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
OPENAI_MODEL=gpt-4o-mini
```

Without OpenAI, resume upload still works using basic keyword extraction.

4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Apply workflows

### Manual apply (default)

1. Select a job → **Analyze fit** → **Prepare to apply**
2. Open the posting, copy materials from the apply kit, submit on the company site
3. Click **I submitted — mark applied**

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

- Auto-submit only runs when enabled in Apply profile and confidence meets your threshold.
- Greenhouse and Lever are supported for assist fill and Playwright; other ATS types use manual apply.
- Use **Mark applied** after you submit an application.
- Without Adzuna keys, manual tracking still works fully.

## API

- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/{id}/status`
- `POST /api/jobs/{id}/fit`
- `POST /api/jobs/{id}/description/enrich`
- `GET /api/jobs/{id}/apply`
- `POST /api/jobs/{id}/apply/prepare`
- `POST /api/jobs/{id}/apply/assist`
- `POST /api/jobs/{id}/apply/auto`
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
