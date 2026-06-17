# Career Agent Apply Helper (Phase 2)

Chrome extension that fills **Greenhouse** and **Lever** job applications from your local Career Agent app.

## Prerequisites

1. Career Agent running locally (`.\start.ps1` from the project root)
2. Apply profile filled in the web UI (upload resume or enter identity fields)
3. Google Chrome or Chromium-based browser

## Install

1. Start Career Agent:

   ```powershell
   cd I:\jobsearch
   .\start.ps1
   ```

2. Open Chrome and go to `chrome://extensions`

3. Enable **Developer mode** (top right)

4. Click **Load unpacked**

5. Select the `extension` folder in this repository (`I:\jobsearch\extension`)

6. Click the extension icon in the toolbar

7. Confirm API URL is `http://127.0.0.1:8000` and click **Test connection**

## Usage

### From Career Agent (recommended)

1. Select a job with a Greenhouse or Lever posting URL
2. Click **Prepare to apply** (optional but generates tailored materials)
3. Click **Browser assist fill** — opens the posting with a `career_agent_job` query param
4. On the application page, click the floating **Fill from Career Agent** button
5. Review filled fields and resume, then submit manually on the company site
6. Back in Career Agent, click **I submitted — mark applied**

### Without assist URL

If you open a posting that matches a job already in your pipeline, the extension can resolve the job by URL. Click **Fill from Career Agent** on supported ATS pages.

## What gets filled

- Name, email, phone, location
- LinkedIn URL
- Cover letter (when available in apply kit)
- Saved answers matched to textarea labels
- Resume file (from your uploaded resume)

## Supported sites

- `*.greenhouse.io` (boards, job-boards, embeds)
- `jobs.lever.co`

## Troubleshooting

| Problem | Fix |
|--------|-----|
| Test connection fails | Run `.\start.ps1` and confirm http://127.0.0.1:8000/api/health returns `{"status":"ok"}` |
| No matching job | Add the job in Career Agent first, or use **Browser assist fill** from the job detail panel |
| Fields not filled | Complete apply profile (email required); some custom questions may need manual entry |
| Resume not attached | Upload a resume in Career Agent; reload the application page and click fill again |
