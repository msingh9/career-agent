const API = "/api";

const statusLabels = {
  new: "New",
  reviewing: "Reviewing",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  passed: "Passed",
  withdrawn: "Withdrawn",
  ignored: "Ignored",
};

let jobs = [];
let selectedJobId = null;
let targetCompanies = [];
let pendingNlPlan = null;
let applyStatusCache = new Map();

const applyModeLabels = {
  manual_only: "Manual",
  assisted: "Assisted",
  auto_with_review: "Auto (review)",
  auto: "Auto",
};

const jobsTableBody = document.getElementById("jobsTableBody");
const jobDetail = document.getElementById("jobDetail");
const filterQuery = document.getElementById("filterQuery");
const filterStatus = document.getElementById("filterStatus");
const searchMessage = document.getElementById("searchMessage");
const statsRow = document.getElementById("statsRow");
const pipelineView = document.getElementById("pipelineView");
const dashboardView = document.getElementById("dashboardView");
const dashboardCards = document.getElementById("dashboardCards");
const recentJobs = document.getElementById("recentJobs");
const viewTitle = document.getElementById("viewTitle");
const viewSubtitle = document.getElementById("viewSubtitle");
const jobAssistant = document.getElementById("jobAssistant");

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || "Request failed");
  }
  return response.status === 204 ? null : response.json();
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function badge(status) {
  return `<span class="badge ${status}">${statusLabels[status] || status}</span>`;
}

function getFilteredJobs() {
  const q = filterQuery.value.trim().toLowerCase();
  const status = filterStatus.value;
  return jobs.filter((job) => {
    if (!status && job.status === "ignored") return false;
    const matchesStatus = !status || job.status === status;
    const haystack = `${job.title} ${job.company} ${job.notes || ""}`.toLowerCase();
    const matchesQuery = !q || haystack.includes(q);
    return matchesStatus && matchesQuery;
  });
}

function fitScoreClass(score) {
  if (score >= 80) return "strong";
  if (score >= 60) return "moderate";
  if (score >= 40) return "weak";
  return "poor";
}

function fitBadge(job) {
  if (job.fit_score == null) {
    return '<span class="fit-badge empty">—</span>';
  }
  return `<span class="fit-badge ${fitScoreClass(job.fit_score)}" title="${job.fit_verdict || ""}">${job.fit_score}</span>`;
}

function jobFitFromJob(job) {
  if (job.fit_score == null) {
    return null;
  }
  return {
    score: job.fit_score,
    verdict: job.fit_verdict,
    summary: job.fit_summary,
    strengths: job.fit_strengths || [],
    gaps: job.fit_gaps || [],
    method: job.fit_method,
    message: job.fit_message,
    analyzed_at: job.fit_analyzed_at,
  };
}

function applyModeBadge(job) {
  if (!job.apply_mode) {
    return '<span class="apply-badge empty">—</span>';
  }
  const label = applyModeLabels[job.apply_mode] || job.apply_mode;
  const confidence =
    job.apply_confidence != null ? `<span class="apply-confidence">${job.apply_confidence}%</span>` : "";
  return `<span class="apply-badge ${job.apply_mode}" title="Apply mode">${label}${confidence}</span>`;
}

async function copyText(text, button) {
  await navigator.clipboard.writeText(text);
  const original = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => {
    button.textContent = original;
  }, 1500);
}

function renderApplyPanel(job, status) {
  const feasibility = status?.feasibility;
  const kit = status?.kit;

  if (!feasibility) {
    return `
      <section class="apply-card">
        <div class="fit-header">
          <div>
            <h4>Apply</h4>
            <p class="hint">Loading apply options...</p>
          </div>
        </div>
      </section>`;
  }

  const materials = kit?.materials;
  const checklist = kit?.checklist || [];
  const copyFields = kit?.copy_fields || {};
  const canAssist = ["greenhouse", "lever"].includes(feasibility.ats_type) && feasibility.confidence >= 60;
  const canAutoFill = canAssist;
  const canAutoSubmit = feasibility.can_auto_submit;

  return `
    <section class="apply-card">
      <div class="fit-header">
        <div>
          <h4>Apply</h4>
          <p class="hint">${feasibility.recommended_action}</p>
        </div>
        <button class="btn primary" id="prepareApplyBtn" type="button">
          ${kit ? "Refresh apply kit" : "Prepare to apply"}
        </button>
      </div>
      <div class="apply-mode-row">
        <span class="apply-badge ${feasibility.apply_mode}">${applyModeLabels[feasibility.apply_mode] || feasibility.apply_mode}</span>
        <span class="apply-confidence-pill ${fitScoreClass(feasibility.confidence)}">${feasibility.confidence}% confidence</span>
        <span class="hint">ATS: ${feasibility.ats_type}</span>
      </div>
      <ul class="apply-reasons">
        ${feasibility.reasons.map((reason) => `<li>${reason}</li>`).join("")}
      </ul>
      <div class="apply-actions-row">
        ${
          canAssist
            ? `<button class="btn secondary" id="assistFillBtn" type="button">Browser assist fill</button>`
            : ""
        }
        ${
          canAutoFill
            ? `<button class="btn secondary" id="autoFillBtn" type="button">Auto-fill form (no submit)</button>`
            : ""
        }
        ${
          canAutoSubmit
            ? `<button class="btn primary" id="autoSubmitBtn" type="button">Auto-apply (submit)</button>`
            : ""
        }
      </div>
      <p class="hint">Phase 2: install the Chrome extension from <code>extension/</code> for in-browser fill. Phase 3: auto-fill uses Playwright locally.</p>
      ${
        kit
          ? `
        <div class="apply-kit">
          <strong>Checklist</strong>
          <ul class="fit-list">
            ${checklist.map((item) => `<li>${item.label}</li>`).join("")}
          </ul>
          ${
            Object.keys(copyFields).length
              ? `
            <strong>Copy fields</strong>
            <div class="apply-copy-grid">
              ${Object.entries(copyFields)
                .map(
                  ([key, value]) => `
                <div class="apply-copy-item">
                  <div class="hint">${key}</div>
                  <div id="copy-field-${key}">${value}</div>
                  <button class="btn secondary copy-btn" type="button" data-copy-target="copy-field-${key}">Copy</button>
                </div>`
                )
                .join("")}
            </div>`
              : ""
          }
          ${
            materials
              ? `
            <strong>Materials</strong>
            <div class="apply-material">
              <div class="apply-material-header">
                <span>Cover letter</span>
                <button class="btn secondary copy-btn" type="button" data-copy-target="copy-cover-letter">Copy</button>
              </div>
              <pre class="apply-text" id="copy-cover-letter">${materials.cover_letter}</pre>
            </div>
            <div class="apply-material">
              <div class="apply-material-header">
                <span>Outreach email</span>
                <button class="btn secondary copy-btn" type="button" data-copy-target="copy-outreach-email">Copy</button>
              </div>
              <pre class="apply-text" id="copy-outreach-email">${materials.outreach_email}</pre>
            </div>
            <div class="apply-material">
              <div class="apply-material-header">
                <span>Why this role</span>
                <button class="btn secondary copy-btn" type="button" data-copy-target="copy-why-role">Copy</button>
              </div>
              <pre class="apply-text" id="copy-why-role">${materials.why_this_role}</pre>
            </div>
            ${
              materials.answers?.length
                ? materials.answers
                    .map(
                      (item, index) => `
              <div class="apply-material">
                <div class="apply-material-header">
                  <span>${item.question}</span>
                  <button class="btn secondary copy-btn" type="button" data-copy-target="copy-answer-${index}">Copy</button>
                </div>
                <pre class="apply-text" id="copy-answer-${index}">${item.answer}</pre>
              </div>`
                    )
                    .join("")
                : ""
            }`
              : ""
          }
          <div class="apply-actions-row">
            <a class="btn secondary" href="${job.url}" target="_blank" rel="noopener noreferrer">Open posting</a>
            <button class="btn primary" id="completeApplyBtn" type="button">I submitted — mark applied</button>
          </div>
          ${status.prepared_at ? `<p class="hint">Kit prepared ${formatDate(status.prepared_at)}</p>` : ""}
        </div>`
          : `<p class="hint">Prepare an apply kit to generate tailored materials. Use browser assist or auto-fill when confidence is high enough.</p>`
      }
    </section>`;
}

function renderJobsTable() {
  const rows = getFilteredJobs();
  jobsTableBody.innerHTML = rows
    .map(
      (job) => `
      <tr data-id="${job.id}" class="${job.id === selectedJobId ? "selected" : ""}">
        <td>
          <div>${job.title}</div>
          ${
            job.description_summary
              ? `<div class="job-summary-snippet">${truncateText(job.description_summary, 120)}</div>`
              : ""
          }
        </td>
        <td>${job.company}</td>
        <td>${job.location || "-"}</td>
        <td>${fitBadge(job)}</td>
        <td>${applyModeBadge(job)}</td>
        <td>${badge(job.status)}</td>
        <td>${job.source}</td>
        <td>${formatDate(job.updated_at)}</td>
        <td class="row-actions">
          <a class="link-btn" href="${job.url}" target="_blank" rel="noopener noreferrer">Open</a>
          ${
            job.status === "ignored"
              ? ""
              : `<button class="link-btn" type="button" data-ignore="${job.id}">Ignore</button>`
          }
        </td>
      </tr>`
    )
    .join("");

  document.querySelectorAll("#jobsTableBody tr").forEach((row) => {
    row.addEventListener("click", async (event) => {
      if (event.target.closest("a, button")) return;
      selectedJobId = Number(row.dataset.id);
      renderJobsTable();
      renderJobDetail();
      await refreshJobApplyStatus(selectedJobId);
      await ensureJobDescription(selectedJobId);
    });
  });

  document.querySelectorAll("[data-ignore]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await updateStatus(Number(button.dataset.ignore), "ignored");
    });
  });
}

function renderFitPanel(job, fit) {
  if (!fit) {
    return `
      <section class="fit-card">
        <div class="fit-header">
          <div>
            <h4>Fit analysis</h4>
            <p class="hint">Compare this role to your resume and profile before you apply manually.</p>
          </div>
          <button class="btn secondary" id="analyzeFitBtn" type="button">Analyze fit</button>
        </div>
      </section>`;
  }

  return `
    <section class="fit-card">
      <div class="fit-header">
        <div>
          <h4>Fit analysis</h4>
          <p class="hint">Guidance only — you apply manually on the company site.</p>
        </div>
        <button class="btn secondary" id="analyzeFitBtn" type="button">Re-analyze</button>
      </div>
      <div class="fit-score-row">
        <div class="fit-score ${fitScoreClass(fit.score)}">
          <strong>${fit.score}</strong>
          <span>/ 100</span>
        </div>
        <div>
          <div class="fit-verdict">${fit.verdict}</div>
          <p class="fit-summary">${fit.summary}</p>
        </div>
      </div>
      <div class="fit-columns">
        <div>
          <strong>Strengths</strong>
          <ul class="fit-list">
            ${fit.strengths.map((item) => `<li>${item}</li>`).join("")}
          </ul>
        </div>
        <div>
          <strong>Gaps</strong>
          <ul class="fit-list">
            ${fit.gaps.map((item) => `<li>${item}</li>`).join("")}
          </ul>
        </div>
      </div>
      ${fit.message ? `<p class="hint">${fit.message}</p>` : ""}
      ${fit.analyzed_at ? `<p class="hint">Analyzed ${formatDate(fit.analyzed_at)}</p>` : ""}
    </section>`;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function truncateText(text, limit = 140) {
  if (!text) return "";
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= limit) return cleaned;
  return `${cleaned.slice(0, limit - 1)}…`;
}

function renderDescriptionPanel(job) {
  if (!job.description_summary) {
    return `
      <section class="description-card">
        <div class="fit-header">
          <div>
            <h4>Role summary</h4>
            <p class="hint">Fetching job description…</p>
          </div>
          <button class="btn secondary" id="refreshDescriptionBtn" type="button">Fetch summary</button>
        </div>
      </section>`;
  }

  return `
    <section class="description-card">
      <div class="fit-header">
        <div>
          <h4>Role summary</h4>
          <p class="hint">Read this without opening the posting${
            job.description_enriched_at ? ` · updated ${formatDate(job.description_enriched_at)}` : ""
          }</p>
        </div>
        <button class="btn secondary" id="refreshDescriptionBtn" type="button">Refresh</button>
      </div>
      <div class="job-summary-text">${escapeHtml(job.description_summary).replace(/\n/g, "<br>")}</div>
    </section>`;
}

function renderJobDetail() {
  const job = jobs.find((item) => item.id === selectedJobId);
  if (!job) {
    jobDetail.className = "detail-card empty";
    jobDetail.innerHTML = `
      <h3>Select a job</h3>
      <p>Choose a role to review details, update status, add notes, and open the posting.</p>`;
    return;
  }

  jobDetail.className = "detail-card";
  jobDetail.innerHTML = `
    <div class="detail-header">
      <div>
        <h3>${job.title}</h3>
        <p>${job.company}${job.location ? ` · ${job.location}` : ""}</p>
      </div>
      ${badge(job.status)}
    </div>
    <div class="detail-meta">
      <div><strong>Source:</strong> ${job.source}</div>
      <div><strong>Discovered:</strong> ${formatDate(job.discovered_at)}</div>
      <div><strong>Salary:</strong> ${job.salary || "Not listed"}</div>
      <div><strong>URL:</strong> <a class="link-btn" href="${job.url}" target="_blank" rel="noopener">${job.url}</a></div>
    </div>
    ${renderDescriptionPanel(job)}
    ${renderFitPanel(job, jobFitFromJob(job))}
    ${renderApplyPanel(job, applyStatusCache.get(job.id))}
    <div class="detail-actions">
      <a class="btn secondary" href="${job.url}" target="_blank" rel="noopener noreferrer">Open posting</a>
      <button class="btn secondary" data-status="reviewing">Mark reviewing</button>
      <button class="btn primary" data-status="applied">Mark applied</button>
      <button class="btn secondary" data-status="interview">Mark interview</button>
      <button class="btn secondary" data-status="rejected">Mark rejected</button>
      <button class="btn secondary" data-status="offer">Mark offer</button>
      <button class="btn secondary" data-status="passed">Mark passed</button>
      <button class="btn secondary" data-status="ignored">Ignore</button>
      <button class="btn secondary" id="deleteJobBtn">Delete</button>
    </div>
    <label>Notes</label>
    <textarea id="jobNotes">${job.notes || ""}</textarea>
    <button class="btn secondary" id="saveNotesBtn">Save notes</button>
    <div class="timeline">
      <strong>Timeline</strong>
      ${(job.events || [])
        .slice()
        .reverse()
        .map(
          (event) => `
          <div class="timeline-item">
            <div>${badge(event.status)} · ${formatDate(event.created_at)}</div>
            <div>${event.note || ""}</div>
          </div>`
        )
        .join("")}
    </div>
  `;

  jobDetail.querySelectorAll("[data-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      await updateStatus(job.id, button.dataset.status);
    });
  });

  document.getElementById("saveNotesBtn").addEventListener("click", async () => {
    const notes = document.getElementById("jobNotes").value;
    await api(`/jobs/${job.id}`, {
      method: "PATCH",
      body: JSON.stringify({ notes }),
    });
    await loadJobs();
  });

  document.getElementById("deleteJobBtn").addEventListener("click", async () => {
    if (!confirm("Delete this job from your tracker?")) return;
    await api(`/jobs/${job.id}`, { method: "DELETE" });
    selectedJobId = null;
    await loadJobs();
  });

  const analyzeFitBtn = document.getElementById("analyzeFitBtn");
  if (analyzeFitBtn) {
    analyzeFitBtn.addEventListener("click", async () => {
      analyzeFitBtn.disabled = true;
      analyzeFitBtn.textContent = "Analyzing...";
      try {
        await api(`/jobs/${job.id}/fit`, { method: "POST" });
        await loadJobs();
      } catch (error) {
        analyzeFitBtn.disabled = false;
        analyzeFitBtn.textContent = job.fit_score == null ? "Analyze fit" : "Re-analyze";
        alert(error.message);
      }
    });
  }

  jobDetail.querySelectorAll(".copy-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        await copyText(target.textContent, button);
      } catch (error) {
        alert("Could not copy to clipboard.");
      }
    });
  });

  const prepareApplyBtn = document.getElementById("prepareApplyBtn");
  if (prepareApplyBtn) {
    prepareApplyBtn.addEventListener("click", async () => {
      prepareApplyBtn.disabled = true;
      prepareApplyBtn.textContent = "Preparing...";
      try {
        const result = await api(`/jobs/${job.id}/apply/prepare`, { method: "POST" });
        applyStatusCache.set(job.id, {
          job_id: job.id,
          feasibility: result.feasibility,
          kit: result.kit,
          prepared_at: result.prepared_at,
          latest_attempt_status: "prepared",
        });
        await loadJobs();
        searchMessage.textContent = result.message;
      } catch (error) {
        prepareApplyBtn.disabled = false;
        prepareApplyBtn.textContent = applyStatusCache.get(job.id)?.kit ? "Refresh apply kit" : "Prepare to apply";
        alert(error.message);
      }
    });
  }

  const completeApplyBtn = document.getElementById("completeApplyBtn");
  if (completeApplyBtn) {
    completeApplyBtn.addEventListener("click", async () => {
      try {
        await api(`/jobs/${job.id}/apply/complete`, {
          method: "POST",
          body: JSON.stringify({ note: "Application submitted manually on company site" }),
        });
        await loadJobs();
        searchMessage.textContent = "Marked as applied.";
      } catch (error) {
        alert(error.message);
      }
    });
  }

  const assistFillBtn = document.getElementById("assistFillBtn");
  if (assistFillBtn) {
    assistFillBtn.addEventListener("click", async () => {
      assistFillBtn.disabled = true;
      try {
        const result = await api(`/jobs/${job.id}/apply/assist`, { method: "POST" });
        window.open(result.url, "_blank", "noopener,noreferrer");
        searchMessage.textContent = result.message;
      } catch (error) {
        alert(error.message);
      } finally {
        assistFillBtn.disabled = false;
      }
    });
  }

  const autoFillBtn = document.getElementById("autoFillBtn");
  if (autoFillBtn) {
    autoFillBtn.addEventListener("click", async () => {
      const confirmed = confirm(
        "Auto-fill will open the application in a visible browser window, fill fields, and leave it open for your review. It will not submit. Continue?"
      );
      if (!confirmed) return;
      autoFillBtn.disabled = true;
      autoFillBtn.textContent = "Filling...";
      try {
        const result = await api(`/jobs/${job.id}/apply/auto`, {
          method: "POST",
          body: JSON.stringify({ confirmed: true, submit: false }),
        });
        searchMessage.textContent = `${result.message} Fields: ${result.filled_fields.join(", ")}`;
        await loadJobs();
      } catch (error) {
        alert(error.message);
      } finally {
        autoFillBtn.disabled = false;
        autoFillBtn.textContent = "Auto-fill form (no submit)";
      }
    });
  }

  const autoSubmitBtn = document.getElementById("autoSubmitBtn");
  if (autoSubmitBtn) {
    autoSubmitBtn.addEventListener("click", async () => {
      const confirmed = confirm(
        "Auto-apply will fill and submit this application via Playwright. Only continue if you have reviewed the apply kit. Submit now?"
      );
      if (!confirmed) return;
      autoSubmitBtn.disabled = true;
      autoSubmitBtn.textContent = "Submitting...";
      try {
        const result = await api(`/jobs/${job.id}/apply/auto`, {
          method: "POST",
          body: JSON.stringify({ confirmed: true, submit: true }),
        });
        searchMessage.textContent = result.message;
        await loadJobs();
      } catch (error) {
        alert(error.message);
      } finally {
        autoSubmitBtn.disabled = false;
        autoSubmitBtn.textContent = "Auto-apply (submit)";
      }
    });
  }
  const refreshDescriptionBtn = document.getElementById("refreshDescriptionBtn");
  if (refreshDescriptionBtn) {
    refreshDescriptionBtn.addEventListener("click", async () => {
      await enrichJobDescription(job.id, true);
    });
  }

  if (!job.description_summary) {
    ensureJobDescription(job.id);
  }
}

async function enrichJobDescription(jobId, force = false) {
  const job = jobs.find((item) => item.id === jobId);
  if (!job) return;
  if (!force && job.description_summary) return;

  const button = document.getElementById("refreshDescriptionBtn");
  if (button) {
    button.disabled = true;
    button.textContent = "Fetching...";
  }

  try {
    const result = await api(`/jobs/${jobId}/description/enrich`, { method: "POST" });
    const index = jobs.findIndex((item) => item.id === jobId);
    if (index >= 0) {
      jobs[index] = {
        ...jobs[index],
        description: result.description,
        description_summary: result.description_summary,
        description_enriched_at: result.description_enriched_at,
      };
    }
    renderJobsTable();
    if (selectedJobId === jobId) {
      renderJobDetail();
    }
  } catch (error) {
    if (selectedJobId === jobId) {
      const panel = jobDetail.querySelector(".description-card .hint");
      if (panel) panel.textContent = error.message;
    }
  }
}

async function ensureJobDescription(jobId) {
  const job = jobs.find((item) => item.id === jobId);
  if (!job || job.description_summary) return;
  await enrichJobDescription(jobId);
}

async function refreshJobApplyStatus(jobId) {
  try {
    const status = await api(`/jobs/${jobId}/apply`);
    applyStatusCache.set(jobId, status);
    if (selectedJobId === jobId) {
      renderJobDetail();
    }
  } catch (error) {
    if (selectedJobId === jobId) {
      applyStatusCache.set(jobId, null);
    }
  }
}

function renderStats() {
  const counts = {};
  jobs.forEach((job) => {
    if (job.status === "ignored") return;
    counts[job.status] = (counts[job.status] || 0) + 1;
  });

  statsRow.classList.remove("hidden");
  statsRow.innerHTML = Object.entries(counts)
    .map(
      ([status, count]) => `
      <div class="stat-card">
        <span>${statusLabels[status] || status}</span>
        <strong>${count}</strong>
      </div>`
    )
    .join("");
}

async function renderDashboard() {
  const data = await api("/dashboard");
  dashboardCards.innerHTML = Object.entries(data.by_status)
    .filter(([, count]) => count > 0)
    .map(
      ([status, count]) => `
      <div class="dashboard-card">
        <span>${statusLabels[status] || status}</span>
        <strong>${count}</strong>
      </div>`
    )
    .join("");

  recentJobs.innerHTML = data.recent
    .map(
      (job) => `
      <div class="timeline-item">
        <div><strong>${job.title}</strong> · ${job.company}</div>
        <div>${badge(job.status)} · ${formatDate(job.updated_at)}</div>
      </div>`
    )
    .join("");
}

function splitCsv(value) {
  return value.split(",").map((v) => v.trim()).filter(Boolean);
}

function joinCsv(values) {
  return (values || []).join(", ");
}

function fillProfileForm(profile) {
  document.getElementById("profileSeniority").value = profile.seniority || "";
  document.getElementById("searchTitles").value = joinCsv(profile.titles);
  document.getElementById("searchKeywords").value = joinCsv(profile.keywords);
  document.getElementById("searchSkills").value = joinCsv(profile.skills);
  document.getElementById("searchIndustries").value = joinCsv(profile.industries);
  document.getElementById("searchLocations").value = joinCsv(profile.locations);
  document.getElementById("searchExclude").value = joinCsv(profile.exclude_keywords);
  document.getElementById("profileSummary").value = profile.summary || "";

  const resumeStatus = document.getElementById("resumeStatus");
  const removeBtn = document.getElementById("removeResumeBtn");
  if (profile.resume_filename) {
    const uploaded = profile.resume_uploaded_at
      ? ` · uploaded ${formatDate(profile.resume_uploaded_at)}`
      : "";
    resumeStatus.textContent = `${profile.resume_filename}${uploaded}`;
    removeBtn.classList.remove("hidden");
  } else {
    resumeStatus.textContent = profile.has_openai
      ? "No resume uploaded. AI extraction is available."
      : "No resume uploaded. Add OPENAI_API_KEY for AI extraction, or use basic extraction.";
    removeBtn.classList.add("hidden");
  }
}

function getProfilePayload() {
  return {
    seniority: document.getElementById("profileSeniority").value.trim() || null,
    titles: splitCsv(document.getElementById("searchTitles").value),
    keywords: splitCsv(document.getElementById("searchKeywords").value),
    skills: splitCsv(document.getElementById("searchSkills").value),
    industries: splitCsv(document.getElementById("searchIndustries").value),
    locations: splitCsv(document.getElementById("searchLocations").value),
    exclude_keywords: splitCsv(document.getElementById("searchExclude").value),
    summary: document.getElementById("profileSummary").value.trim() || null,
  };
}

function getSearchPayload() {
  const profile = getProfilePayload();
  return {
    ...profile,
    max_results: 50,
  };
}

async function loadApplyProfile() {
  const profile = await api("/profile/apply");
  fillApplyProfileForm(profile);
}

function fillApplyProfileForm(profile, statusMessage = null) {
  const identity = profile.identity || {};
  document.getElementById("applyFullName").value = identity.full_name || "";
  document.getElementById("applyEmail").value = identity.email || "";
  document.getElementById("applyPhone").value = identity.phone || "";
  document.getElementById("applyLinkedin").value = identity.linkedin_url || "";
  document.getElementById("applyLocation").value = identity.location || "";
  document.getElementById("applyWorkAuth").value = identity.work_authorization || "";
  document.getElementById("applySponsorship").checked = Boolean(identity.requires_sponsorship);

  const settings = profile.settings || {};
  document.getElementById("applyAutoEnabled").checked = Boolean(settings.auto_apply_enabled);
  document.getElementById("applyAlwaysConfirm").checked = settings.always_confirm_submit !== false;

  const container = document.getElementById("savedAnswersList");
  container.innerHTML = (profile.saved_answers || [])
    .map(
      (item, index) => `
      <label>${item.label}</label>
      <textarea class="saved-answer" data-answer-key="${item.key}" data-answer-label="${item.label}">${item.answer || ""}</textarea>`
    )
    .join("");

  const message = document.getElementById("applyProfileMessage");
  if (statusMessage) {
    message.textContent = statusMessage;
  } else if (profile.missing_fields?.length) {
    message.textContent = `Missing for best results: ${profile.missing_fields.join(", ")}`;
  } else {
    message.textContent = "Apply profile complete.";
  }
}

function getApplyProfilePayload() {
  const savedAnswers = Array.from(document.querySelectorAll(".saved-answer")).map((field) => ({
    key: field.dataset.answerKey,
    label: field.dataset.answerLabel,
    answer: field.value.trim(),
  }));

  return {
    identity: {
      full_name: document.getElementById("applyFullName").value.trim(),
      email: document.getElementById("applyEmail").value.trim(),
      phone: document.getElementById("applyPhone").value.trim(),
      linkedin_url: document.getElementById("applyLinkedin").value.trim(),
      website: "",
      location: document.getElementById("applyLocation").value.trim(),
      work_authorization: document.getElementById("applyWorkAuth").value.trim(),
      requires_sponsorship: document.getElementById("applySponsorship").checked,
    },
    saved_answers: savedAnswers,
    settings: {
      auto_apply_enabled: document.getElementById("applyAutoEnabled").checked,
      min_auto_confidence: 85,
      always_confirm_submit: document.getElementById("applyAlwaysConfirm").checked,
    },
  };
}

async function saveApplyProfile() {
  const profile = await api("/profile/apply", {
    method: "PUT",
    body: JSON.stringify(getApplyProfilePayload()),
  });
  fillApplyProfileForm(profile);
  document.getElementById("applyProfileMessage").textContent = "Apply profile saved.";
}

async function loadProfile() {
  const profile = await api("/profile");
  fillProfileForm(profile);
}

async function saveProfile() {
  const profile = await api("/profile", {
    method: "PUT",
    body: JSON.stringify(getProfilePayload()),
  });
  fillProfileForm(profile);
  searchMessage.textContent = "Search profile saved.";
}
async function loadJobs() {
  jobs = await api("/jobs");
  renderStats();
  renderJobsTable();
  renderJobDetail();
  if (!dashboardView.classList.contains("hidden")) {
    await renderDashboard();
  }
}

async function updateStatus(jobId, status) {
  await api(`/jobs/${jobId}/status`, {
    method: "POST",
    body: JSON.stringify({
      status,
      note: `Marked as ${statusLabels[status] || status}`,
    }),
  });
  if (status === "ignored" && selectedJobId === jobId) {
    selectedJobId = null;
  }
  await loadJobs();
}

document.getElementById("runSearchBtn").addEventListener("click", async () => {
  searchMessage.textContent = "Searching...";
  try {
    await saveProfile();
    const result = await api("/agent/search", {
      method: "POST",
      body: JSON.stringify(getSearchPayload()),
    });
    searchMessage.textContent = result.message;
    await loadJobs();
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

document.getElementById("extractApplyProfileBtn").addEventListener("click", async () => {
  const button = document.getElementById("extractApplyProfileBtn");
  button.disabled = true;
  button.textContent = "Extracting...";
  try {
    const profile = await api("/profile/apply/extract-from-resume", { method: "POST" });
    fillApplyProfileForm(profile, profile.message);
  } catch (error) {
    document.getElementById("applyProfileMessage").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Refresh from resume";
  }
});

document.getElementById("saveApplyProfileBtn").addEventListener("click", async () => {
  try {
    await saveApplyProfile();
  } catch (error) {
    document.getElementById("applyProfileMessage").textContent = error.message;
  }
});

document.getElementById("saveProfileBtn").addEventListener("click", async () => {
  try {
    await saveProfile();
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

document.getElementById("resumeFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  searchMessage.textContent = "Analyzing resume...";
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(`${API}/profile/resume`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || "Resume upload failed");
    }
    const profile = await response.json();
    fillProfileForm(profile);
    await loadApplyProfile();
    searchMessage.textContent = profile.message;
  } catch (error) {
    searchMessage.textContent = error.message;
  } finally {
    event.target.value = "";
  }
});

document.getElementById("removeResumeBtn").addEventListener("click", async () => {
  try {
    const profile = await api("/profile/resume", { method: "DELETE" });
    fillProfileForm(profile);
    searchMessage.textContent = "Resume removed. Your search criteria are unchanged.";
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

document.getElementById("googleJobsBtn").addEventListener("click", async () => {
  const titles = document.getElementById("searchTitles").value;
  const keywords = document.getElementById("searchKeywords").value;
  const result = await api(`/agent/google-jobs-url?titles=${encodeURIComponent(titles)}&keywords=${encodeURIComponent(keywords)}`);
  window.open(result.url, "_blank", "noopener");
});

document.getElementById("addJobBtn").addEventListener("click", async () => {
  const payload = {
    title: document.getElementById("manualTitle").value.trim(),
    company: document.getElementById("manualCompany").value.trim(),
    location: document.getElementById("manualLocation").value.trim() || null,
    url: document.getElementById("manualUrl").value.trim(),
    source: "manual",
  };
  if (!payload.title || !payload.company || !payload.url) {
    alert("Title, company, and URL are required.");
    return;
  }
  await api("/jobs", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("manualTitle").value = "";
  document.getElementById("manualCompany").value = "";
  document.getElementById("manualLocation").value = "";
  document.getElementById("manualUrl").value = "";
  await loadJobs();
});

filterQuery.addEventListener("input", renderJobsTable);
filterStatus.addEventListener("change", renderJobsTable);

document.getElementById("deleteAllJobsBtn").addEventListener("click", async () => {
  const count = jobs.length;
  if (!count) {
    alert("There are no jobs to delete.");
    return;
  }
  const confirmed = confirm(
    `Delete all ${count} job${count === 1 ? "" : "s"} from your tracker? This cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const result = await api("/jobs", { method: "DELETE" });
    selectedJobId = null;
    await loadJobs();
    searchMessage.textContent = `Deleted ${result.deleted} job${result.deleted === 1 ? "" : "s"}.`;
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

async function loadCompanies() {
  targetCompanies = await api("/companies");
  renderCompanyList();
}

function renderCompanyList() {
  const container = document.getElementById("companyList");
  if (!targetCompanies.length) {
    container.innerHTML = `<p class="hint">No target companies yet.</p>`;
    return;
  }

  container.innerHTML = targetCompanies
    .map(
      (company) => `
      <div class="company-item" data-id="${company.id}">
        <div class="company-item-header">
          <div>
            <strong>${company.name}</strong>
            <span class="ats-badge ${company.ats_type}">${company.ats_type}</span>
          </div>
          <span class="company-meta">${company.enabled ? "Enabled" : "Disabled"}</span>
        </div>
        <div class="company-meta">${company.careers_url}</div>
        <div class="company-meta">
          ${company.last_scraped_at ? `Last scanned ${formatDate(company.last_scraped_at)}` : "Not scanned yet"}
          ${company.last_job_count != null ? ` · ${company.last_job_count} jobs` : ""}
        </div>
        <div class="company-actions">
          <button class="btn secondary" data-action="toggle">${company.enabled ? "Disable" : "Enable"}</button>
          <button class="btn secondary" data-action="delete">Remove</button>
        </div>
      </div>`
    )
    .join("");

  container.querySelectorAll(".company-item").forEach((item) => {
    const companyId = Number(item.dataset.id);
    item.querySelector('[data-action="toggle"]').addEventListener("click", async () => {
      const company = targetCompanies.find((entry) => entry.id === companyId);
      await api(`/companies/${companyId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !company.enabled }),
      });
      await loadCompanies();
    });
    item.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      const company = targetCompanies.find((entry) => entry.id === companyId);
      if (!confirm(`Remove ${company.name} from target companies?`)) return;
      await api(`/companies/${companyId}`, { method: "DELETE" });
      await loadCompanies();
    });
  });
}

function resetNlPlanUi() {
  pendingNlPlan = null;
  document.getElementById("nlJobPlanPanel").classList.add("hidden");
  document.getElementById("nlJobExecuteBtn").classList.add("hidden");
  document.getElementById("nlJobCancelBtn").classList.add("hidden");
}

function renderNlPlan(plan) {
  pendingNlPlan = plan;
  const panel = document.getElementById("nlJobPlanPanel");
  const executeBtn = document.getElementById("nlJobExecuteBtn");
  const cancelBtn = document.getElementById("nlJobCancelBtn");

  document.getElementById("nlJobExplanation").textContent = plan.explanation;
  document.getElementById("nlJobMeta").textContent =
    `${plan.affected_count} job(s) matched · action: ${plan.action}` +
    (plan.requires_confirmation ? " · confirmation required" : "");
  document.getElementById("nlJobSql").textContent = plan.sql_preview;

  const preview = document.getElementById("nlJobPreview");
  if (!plan.preview_jobs.length) {
    preview.innerHTML = `<p class="hint">No matching jobs.</p>`;
  } else {
    preview.innerHTML = plan.preview_jobs
      .map(
        (job) => `
        <div class="assistant-preview-item">
          <strong>${job.title}</strong> · ${job.company}
          <div class="hint">${job.location || "No location"} · ${job.status} · ${job.source}</div>
        </div>`
      )
      .join("");
    if (plan.affected_count > plan.preview_jobs.length) {
      preview.innerHTML += `<p class="hint">Showing ${plan.preview_jobs.length} of ${plan.affected_count} matches.</p>`;
    }
  }

  panel.classList.remove("hidden");
  cancelBtn.classList.remove("hidden");

  if (plan.requires_confirmation) {
    const verb = plan.action === "delete" ? "Delete" : plan.action === "ignore" ? "Ignore" : "Apply";
    executeBtn.textContent = `${verb} ${plan.affected_count} job(s)`;
    executeBtn.classList.remove("hidden");
  } else if (plan.action === "list") {
    executeBtn.classList.add("hidden");
  }
}

document.getElementById("nlJobPlanBtn").addEventListener("click", async () => {
  const query = document.getElementById("nlJobQuery").value.trim();
  if (!query) {
    alert("Describe what you want to do with your jobs.");
    return;
  }
  resetNlPlanUi();
  try {
    const plan = await api("/agent/nl-jobs/plan", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    renderNlPlan(plan);
  } catch (error) {
    alert(error.message);
  }
});

document.getElementById("nlJobCancelBtn").addEventListener("click", () => {
  resetNlPlanUi();
});

document.getElementById("nlJobExecuteBtn").addEventListener("click", async () => {
  if (!pendingNlPlan) return;

  const count = pendingNlPlan.affected_count;
  const action = pendingNlPlan.action;
  const verb = action === "delete" ? "delete" : action === "ignore" ? "ignore" : "update";
  const confirmed = confirm(
    `${pendingNlPlan.explanation}\n\nThis will ${verb} ${count} job(s). Continue?`
  );
  if (!confirmed) return;

  try {
    const result = await api("/agent/nl-jobs/execute", {
      method: "POST",
      body: JSON.stringify({ plan: pendingNlPlan, confirmed: true }),
    });
    resetNlPlanUi();
    document.getElementById("nlJobQuery").value = "";
    searchMessage.textContent = result.message;
    selectedJobId = null;
    await loadJobs();
  } catch (error) {
    alert(error.message);
  }
});

document.getElementById("addCompanyBtn").addEventListener("click", async () => {
  const name = document.getElementById("companyName").value.trim();
  const careers_url = document.getElementById("companyUrl").value.trim();
  if (!name || !careers_url) {
    alert("Company name and careers URL are required.");
    return;
  }
  try {
    await api("/companies", {
      method: "POST",
      body: JSON.stringify({ name, careers_url }),
    });
    document.getElementById("companyName").value = "";
    document.getElementById("companyUrl").value = "";
    await loadCompanies();
    searchMessage.textContent = `${name} added to target companies.`;
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

document.getElementById("runCompanySearchBtn").addEventListener("click", async () => {
  searchMessage.textContent = "Searching target companies...";
  try {
    await saveProfile();
    const result = await api("/agent/company-search", {
      method: "POST",
      body: JSON.stringify(getSearchPayload()),
    });
    let message = result.message;
    if (result.details?.length) {
      const summary = result.details
        .map((detail) => {
          if (detail.error) return `${detail.company}: error`;
          return `${detail.company}: +${detail.added}`;
        })
        .join(" · ");
      message += ` ${summary}.`;
    }
    searchMessage.textContent = message;
    await loadCompanies();
    await loadJobs();
  } catch (error) {
    searchMessage.textContent = error.message;
  }
});

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".nav-btn").forEach((btn) => btn.classList.remove("active"));
    button.classList.add("active");
    const view = button.dataset.view;
    if (view === "dashboard") {
      pipelineView.classList.add("hidden");
      jobAssistant.classList.add("hidden");
      dashboardView.classList.remove("hidden");
      statsRow.classList.add("hidden");
      viewTitle.textContent = "Dashboard";
      viewSubtitle.textContent = "Overview of your semiconductor executive search.";
      await renderDashboard();
    } else {
      dashboardView.classList.add("hidden");
      jobAssistant.classList.remove("hidden");
      pipelineView.classList.remove("hidden");
      viewTitle.textContent = "Pipeline";
      viewSubtitle.textContent = "Track discovery, applications, interviews, and outcomes.";
      renderStats();
    }
  });
});

loadProfile()
  .then(() => loadApplyProfile())
  .then(() => Promise.all([loadJobs(), loadCompanies()]))
  .catch((error) => {
    searchMessage.textContent = `Failed to load app: ${error.message}`;
  });
