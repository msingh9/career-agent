# Semiconductor Career Agent

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

## Quick start

1. Open PowerShell in `I:\jobsearch`
2. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Optional: configure job search API keys

```powershell
Copy-Item .env.example .env
```

Get free Adzuna keys from https://developer.adzuna.com/ and set:

```
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
```

Optional: enable AI resume analysis (recommended):

```
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
```

Without OpenAI, resume upload still works using basic keyword extraction.

4. Start the app:

```powershell
.\start.ps1
```

5. Open http://127.0.0.1:8000

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

- Auto-apply is intentionally not included in MVP because each employer ATS differs.
- Use **Mark applied** after you submit an application.
- Without Adzuna keys, manual tracking still works fully.

## API

- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/{id}/status`
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
