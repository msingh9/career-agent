# Career Agent

**Drop in your resume. Get matched to jobs. Apply and track — all in one place.**

Career Agent reads your resume, finds roles that fit, and helps you apply — from a simple chat window. Works for any role or industry.

## What you can do

- **Chat with the agent** — "search jobs from my resume", "search company Stripe", "ignore jobs that aren't senior."
- **Upload your resume** — it's turned into your search criteria automatically.
- **Tune match strictness (1–10)** — 1 = more jobs, 10 = only the best matches.
- **Track your pipeline** — statuses, notes, and fit analysis per job.
- **Auto-fill applications** — the agent opens your real Chrome, follows the link to the actual form, and fills it in for you to review and submit.
- **Multiple profiles** — each person (or search) gets their own resume, jobs, and settings. No passwords.

## Get started

1. Open PowerShell in the project folder and run:

   ```powershell
   .\start.ps1
   ```

2. Open **http://127.0.0.1:8000** and **pick or create a profile**.
3. Upload your resume in the chat's welcome card, then ask: **"search jobs from my resume."**

That's it. To enable job search and AI features, add API keys to `backend/.env` (copy from `.env.example`):
- **Adzuna** (free, for job search): `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` — get them at [developer.adzuna.com](https://developer.adzuna.com/).
- **OpenAI** (recommended, for resume digest + chat): `OPENAI_API_KEY`.

Everything runs locally; your data stays in `data/` on your machine.

## Applying to a job

- **Manual:** open a job → **Prepare to apply** → copy the generated materials → submit on the company site → **Mark applied**.
- **Auto-fill (any site):** first run `.\start-chrome-debug.ps1` once, then click **Auto-fill** on a job. The agent follows the link to the real application form and fills it in your Chrome. **It never submits** — you review and click submit. It stops safely at logins and CAPTCHAs.

## Tips

- If a search returns too few jobs, **lower match strictness** or broaden your keywords/locations (Settings ⚙).
- Auto-fill works best when you're logged into job sites in the debug Chrome window.
- Switch or add profiles anytime from the profile menu (top right).

---

Building on or contributing to Career Agent? See **[README.dev.md](README.dev.md)** for architecture, configuration, the API, and how auto-apply works under the hood.
