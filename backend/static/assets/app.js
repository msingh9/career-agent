"use strict";

/* ------------------------------------------------------------------ */
/* State + helpers                                                      */
/* ------------------------------------------------------------------ */
const USER_KEY = "careerAgentUserId";
const state = {
  userId: null,
  users: [],
  profile: null,
  jobs: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function getUserId() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? Number(raw) : null;
}
function setUserId(id) {
  state.userId = id;
  if (id) localStorage.setItem(USER_KEY, String(id));
  else localStorage.removeItem(USER_KEY);
}

async function apiFetch(path, options = {}) {
  const opts = { ...options };
  opts.headers = { ...(options.headers || {}) };
  if (state.userId) opts.headers["X-User-Id"] = String(state.userId);
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers["Content-Type"]) {
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`/api${path}`, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3500);
}

/* ------------------------------------------------------------------ */
/* Boot + profile gate                                                 */
/* ------------------------------------------------------------------ */
async function init() {
  wireStaticHandlers();
  try {
    state.users = await apiFetch("/users");
  } catch (e) {
    state.users = [];
  }
  const stored = getUserId();
  const valid = stored && state.users.some((u) => u.id === stored);
  if (valid) {
    setUserId(stored);
    await boot();
  } else {
    showGate();
  }
}

function showGate() {
  $("#appShell").classList.add("hidden");
  $("#profileGate").classList.remove("hidden");
  renderProfileGrid();
}

function renderProfileGrid() {
  const grid = $("#profileList");
  grid.innerHTML = "";
  state.users.forEach((u) => {
    const card = document.createElement("button");
    card.className = "profile-tile";
    card.type = "button";
    card.innerHTML = `<div class="avatar">${esc(u.name.charAt(0).toUpperCase())}</div>
      <div class="profile-tile-name">${esc(u.name)}</div>
      <div class="muted small">${u.job_count} jobs${u.has_resume ? " · resume ✓" : ""}</div>`;
    card.addEventListener("click", async () => {
      setUserId(u.id);
      await boot();
    });
    grid.appendChild(card);
  });
}

async function createProfile(name) {
  const created = await apiFetch("/users", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  state.users.push(created);
  setUserId(created.id);
  await boot();
}

async function boot() {
  $("#profileGate").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
  const me = state.users.find((u) => u.id === state.userId);
  $("#currentProfileName").textContent = me ? me.name : "Profile";
  await loadProfileState();
  switchView("chat");
  if (!$("#chatMessages").children.length) {
    addMessage("assistant", `Hi${me ? " " + esc(me.name) : ""}! Tell me what you'd like to do — for example <em>“search jobs based on my resume”</em>, <em>“search company Stripe”</em>, or <em>“ignore jobs that aren't senior”</em>.`);
  }
}

async function loadProfileState() {
  try {
    state.profile = await apiFetch("/profile");
  } catch (_) {
    state.profile = null;
  }
  const hasResume = state.profile && state.profile.resume_filename;
  $("#resumeEmptyState").classList.toggle("hidden", !!hasResume);
}

// Build a full profile PUT body from cached state (so partial updates don't
// wipe extracted criteria — every SearchProfileData field must be sent).
function profilePutBody(overrides = {}) {
  const p = state.profile || {};
  return {
    titles: p.titles || [], keywords: p.keywords || [], locations: p.locations || [],
    skills: p.skills || [], industries: p.industries || [], seniority: p.seniority || null,
    exclude_keywords: p.exclude_keywords || [], summary: p.summary || null,
    match_strictness: p.match_strictness || 5, ...overrides,
  };
}

// Post the resume-digest summary + an inline 1–10 strictness prompt into chat.
function postResumeDigest(res) {
  const titles = (res.titles || []).slice(0, 6).join(", ") || "—";
  const kws = (res.keywords || []).slice(0, 10).join(", ") || "—";
  const strict = res.match_strictness || (state.profile && state.profile.match_strictness) || 5;
  const html = `✅ Resume digested — I set your search criteria.<br>
    <span class="muted small"><strong>Titles:</strong> ${esc(titles)}<br><strong>Keywords:</strong> ${esc(kws)}</span>
    <div class="strictness-block">
      <div><strong>How strict should job matching be?</strong> <span class="muted small">(1 = more jobs · 10 = only best matches)</span></div>
      <div class="strictness-row"><input type="range" min="1" max="10" value="${strict}" class="strictness-slider" /><span class="strictness-val">${strict}</span>/10</div>
      <button class="btn primary sm strictness-search">Search jobs now</button>
    </div>`;
  const bubble = addMessage("assistant", html);
  const slider = bubble.querySelector(".strictness-slider");
  const valEl = bubble.querySelector(".strictness-val");
  slider.addEventListener("input", () => { valEl.textContent = slider.value; });
  slider.addEventListener("change", async () => {
    try {
      await apiFetch("/profile", { method: "PUT", body: JSON.stringify(profilePutBody({ match_strictness: Number(slider.value) })) });
      if (state.profile) state.profile.match_strictness = Number(slider.value);
      toast(`Match strictness set to ${slider.value}/10`);
    } catch (e) { toast(e.message, true); }
  });
  bubble.querySelector(".strictness-search").addEventListener("click", () => sendChat("Search jobs based on my resume"));
}

/* ------------------------------------------------------------------ */
/* View switching                                                      */
/* ------------------------------------------------------------------ */
function switchView(view) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  $("#chatView").classList.toggle("hidden", view !== "chat");
  $("#jobsView").classList.toggle("hidden", view !== "jobs");
  if (view === "jobs") loadJobs();
}

/* ------------------------------------------------------------------ */
/* Chat                                                                */
/* ------------------------------------------------------------------ */
function addMessage(role, html) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `<div class="bubble">${html}</div>`;
  $("#chatMessages").appendChild(wrap);
  $("#chatMessages").scrollTop = $("#chatMessages").scrollHeight;
  return wrap;
}

function jobChipList(jobs) {
  if (!jobs || !jobs.length) return "";
  const items = jobs.slice(0, 12).map((j) =>
    `<button class="job-chip" data-job-id="${j.id}">
       <span class="job-chip-title">${esc(j.title)}</span>
       <span class="muted small">${esc(j.company)}${j.location ? " · " + esc(j.location) : ""}</span>
     </button>`
  ).join("");
  const more = jobs.length > 12 ? `<div class="muted small">+${jobs.length - 12} more in the Jobs tab</div>` : "";
  return `<div class="job-chip-list">${items}</div>${more}`;
}

async function sendChat(message) {
  addMessage("user", esc(message));
  const thinking = addMessage("assistant", `<span class="typing">…</span>`);
  try {
    const res = await apiFetch("/agent/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    thinking.remove();
    let html = esc(res.reply);
    if (res.jobs && res.jobs.length) html += jobChipList(res.jobs);
    const bubble = addMessage("assistant", html);
    if (res.requires_confirmation && res.plan) {
      renderConfirm(bubble, res.plan);
    }
    if (res.action === "search" || res.action === "company_search") {
      state.jobsDirty = true;
      loadProfileState();
    }
    bindJobChips(bubble);
  } catch (e) {
    thinking.remove();
    addMessage("assistant", `<span class="error-text">${esc(e.message)}</span>`);
  }
}

function renderConfirm(bubble, plan) {
  const row = document.createElement("div");
  row.className = "confirm-row";
  row.innerHTML = `<button class="btn danger sm">Confirm</button><button class="btn secondary sm">Cancel</button>`;
  const [confirmBtn, cancelBtn] = row.querySelectorAll("button");
  confirmBtn.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    try {
      const result = await apiFetch("/agent/nl-jobs/execute", {
        method: "POST",
        body: JSON.stringify({ plan, confirmed: true }),
      });
      row.remove();
      addMessage("assistant", esc(result.message));
      state.jobsDirty = true;
    } catch (e) {
      addMessage("assistant", `<span class="error-text">${esc(e.message)}</span>`);
    }
  });
  cancelBtn.addEventListener("click", () => {
    row.remove();
    addMessage("assistant", "Okay, cancelled.");
  });
  bubble.querySelector(".bubble").appendChild(row);
}

function bindJobChips(scope) {
  scope.querySelectorAll(".job-chip").forEach((chip) => {
    chip.addEventListener("click", () => openJobModal(Number(chip.dataset.jobId)));
  });
}

/* ------------------------------------------------------------------ */
/* Jobs view                                                           */
/* ------------------------------------------------------------------ */
function fitBadge(job) {
  if (job.fit_score == null) return "";
  let cls = "low";
  if (job.fit_score >= 80) cls = "high";
  else if (job.fit_score >= 60) cls = "mid";
  return `<span class="fit-badge ${cls}">${job.fit_score}</span>`;
}

const STATUS_LABELS = {
  new: "New", reviewing: "Reviewing", applied: "Applied", interview: "Interview",
  offer: "Offer", rejected: "Rejected", passed: "Passed", withdrawn: "Withdrawn", ignored: "Ignored",
};

async function loadJobs() {
  const statusSel = $("#jobsStatusFilter").value;
  let path = "/jobs";
  const params = [];
  if (statusSel) params.push(`status=${statusSel}`);
  if (statusSel === "ignored") params.push("include_ignored=true");
  if (params.length) path += "?" + params.join("&");
  try {
    state.jobs = await apiFetch(path);
    state.jobsDirty = false;
    renderJobs();
  } catch (e) {
    $("#jobsList").innerHTML = `<p class="error-text">${esc(e.message)}</p>`;
  }
}

function renderJobs() {
  const term = $("#jobsFilter").value.trim().toLowerCase();
  const list = state.jobs.filter((j) =>
    !term || j.title.toLowerCase().includes(term) || j.company.toLowerCase().includes(term)
  );
  $("#jobsCount").textContent = `${list.length} job${list.length === 1 ? "" : "s"}`;
  if (!list.length) {
    $("#jobsList").innerHTML = `<div class="empty-inline muted">No jobs yet. Ask the agent in Chat to search for some.</div>`;
    return;
  }
  $("#jobsList").innerHTML = list.map((job) => `
    <div class="job-row" data-job-id="${job.id}">
      <div class="job-row-main">
        <div class="job-row-title">${fitBadge(job)}<span>${esc(job.title)}</span></div>
        <div class="muted small">${esc(job.company)}${job.location ? " · " + esc(job.location) : ""} · <span class="status-pill ${job.status}">${STATUS_LABELS[job.status] || job.status}</span></div>
      </div>
      <div class="job-row-actions">
        <button class="btn primary sm" data-action="agentic" title="Follow the link and fill the application in your Chrome (no submit)">Auto-fill</button>
        <button class="btn secondary sm" data-action="ignore">Ignore</button>
      </div>
    </div>`).join("");

  $$("#jobsList .job-row").forEach((row) => {
    const id = Number(row.dataset.jobId);
    row.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      openJobModal(id);
    });
    row.querySelector('[data-action="agentic"]').addEventListener("click", () => agenticApply(id));
    row.querySelector('[data-action="ignore"]').addEventListener("click", () => ignoreJob(id));
  });
}

async function ignoreJob(id) {
  try {
    await apiFetch(`/jobs/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status: "ignored", note: "Ignored from jobs list" }),
    });
    toast("Job ignored");
    loadJobs();
  } catch (e) {
    toast(e.message, true);
  }
}

async function agenticApply(id) {
  toast("Agentic apply: following the link and filling in Chrome…");
  try {
    const res = await apiFetch(`/jobs/${id}/apply/agentic`, { method: "POST" });
    toast(res.message, !res.filled_fields.length);
    if (!$("#jobModal").classList.contains("hidden")) openJobModal(id);
    else { state.jobsDirty = true; loadJobs(); }
  } catch (e) {
    toast(e.message, true);
  }
}

async function autoApply(id, submit) {
  toast(submit ? "Auto-applying in Chrome…" : "Auto-filling in Chrome…");
  try {
    const res = await apiFetch(`/jobs/${id}/apply/auto`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true, submit }),
    });
    toast(res.message);
    if ($("#jobModal").classList.contains("hidden") === false) openJobModal(id);
    else loadJobs();
  } catch (e) {
    toast(e.message, true);
  }
}

/* ------------------------------------------------------------------ */
/* Job modal                                                           */
/* ------------------------------------------------------------------ */
async function openJobModal(id) {
  const modal = $("#jobModal");
  const body = $("#jobModalBody");
  modal.classList.remove("hidden");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const [job, apply] = await Promise.all([
      apiFetch(`/jobs/${id}`),
      apiFetch(`/jobs/${id}/apply`).catch(() => null),
    ]);
    renderJobModal(job, apply);
  } catch (e) {
    body.innerHTML = `<p class="error-text">${esc(e.message)}</p>`;
  }
}

function renderJobModal(job, apply) {
  const f = apply && apply.feasibility;
  const hasEmail = state.applyProfile ? !!(state.applyProfile.identity.email || "").trim() : true;
  const isTierA = f && ["greenhouse", "lever"].includes(f.ats_type);
  const statusOptions = Object.keys(STATUS_LABELS)
    .map((s) => `<option value="${s}" ${s === job.status ? "selected" : ""}>${STATUS_LABELS[s]}</option>`)
    .join("");

  const missing = job.ats_missing_keywords || [];
  const atsBlock = job.ats_coverage != null ? `
      <div class="ats-row"><strong>ATS keyword coverage:</strong> ${job.ats_coverage}%${job.ats_coverage < 60 ? ' <span class="ats-warn">— tailor your resume</span>' : ""}</div>
      ${missing.length ? `<div class="muted small">Missing JD keywords (add if true): ${missing.map(esc).join(", ")}</div>` : ""}` : "";
  const fitBlock = job.fit_score != null ? `
    <div class="modal-section">
      <h4>Screening fit ${fitBadge(job)} <span class="muted small">${esc(job.fit_verdict || "")}</span></h4>
      <p class="muted">${esc(job.fit_summary || "")}</p>
      ${atsBlock}
    </div>` : "";

  const feasBlock = f ? `
    <div class="modal-section">
      <h4>Apply</h4>
      <p class="muted small">${esc(f.recommended_action)}</p>
      <div class="apply-meta">
        <span class="tag">${esc(f.apply_mode)}</span>
        <span class="tag">${f.confidence}% confidence</span>
        <span class="tag">ATS: ${esc(f.ats_type)}</span>
      </div>
      <ul class="reasons">${f.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    </div>` : "";

  $("#jobModalBody").innerHTML = `
    <h3>${esc(job.title)}</h3>
    <p class="muted">${esc(job.company)}${job.location ? " · " + esc(job.location) : ""}${job.salary ? " · " + esc(job.salary) : ""}</p>
    <a class="link" href="${esc(job.url)}" target="_blank" rel="noopener">Open posting ↗</a>
    ${fitBlock}
    ${feasBlock}
    <div class="modal-actions">
      <button class="btn secondary sm" id="mAnalyze">Analyze fit</button>
      <button class="btn secondary sm" id="mPrepare">Prepare to apply</button>
      <button class="btn primary sm" id="mAgentic" title="Follow the link to the real form and fill it in your Chrome (no submit)">Agentic apply (fill in Chrome)</button>
      ${isTierA && hasEmail ? `<button class="btn secondary sm" id="mAutoFill">Greenhouse/Lever auto-fill</button>` : ""}
      ${f && f.can_auto_submit ? `<button class="btn primary sm" id="mAutoSubmit">Auto-apply (submit)</button>` : ""}
    </div>
    <p class="hint">Agentic apply follows the posting link to the real application form and fills it in your debug Chrome (port 9333) — it never submits. Stops at logins/CAPTCHAs.</p>
    <div class="modal-section">
      <label>Status</label>
      <select id="mStatus">${statusOptions}</select>
      <label>Notes</label>
      <textarea id="mNotes" rows="3">${esc(job.notes || "")}</textarea>
      <button class="btn secondary sm" id="mSaveNotes">Save notes & status</button>
      <button class="btn secondary sm" id="mMarkApplied">Mark applied</button>
    </div>
    ${job.description_summary ? `<div class="modal-section"><h4>Summary</h4><p class="muted">${esc(job.description_summary)}</p></div>` : ""}
  `;

  const id = job.id;
  $("#mAnalyze").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Analyzing…";
    try { await apiFetch(`/jobs/${id}/fit`, { method: "POST" }); toast("Fit analyzed"); state.jobsDirty = true; openJobModal(id); }
    catch (err) { toast(err.message, true); e.target.disabled = false; }
  });
  $("#mPrepare").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Preparing…";
    try { const r = await apiFetch(`/jobs/${id}/apply/prepare`, { method: "POST" }); toast(r.message); state.jobsDirty = true; openJobModal(id); }
    catch (err) { toast(err.message, true); e.target.disabled = false; }
  });
  $("#mAgentic").addEventListener("click", () => agenticApply(id));
  if ($("#mAutoFill")) $("#mAutoFill").addEventListener("click", () => autoApply(id, false));
  if ($("#mAutoSubmit")) $("#mAutoSubmit").addEventListener("click", () => {
    if (confirm("Submit this application automatically?")) autoApply(id, true);
  });
  $("#mSaveNotes").addEventListener("click", async () => {
    try {
      await apiFetch(`/jobs/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ notes: $("#mNotes").value, status: $("#mStatus").value }),
      });
      toast("Saved");
      state.jobsDirty = true;
    } catch (e) { toast(e.message, true); }
  });
  $("#mMarkApplied").addEventListener("click", async () => {
    try { await apiFetch(`/jobs/${id}/apply/complete`, { method: "POST", body: JSON.stringify({}) }); toast("Marked applied"); openJobModal(id); state.jobsDirty = true; }
    catch (e) { toast(e.message, true); }
  });
}

function closeJobModal() {
  $("#jobModal").classList.add("hidden");
  if (state.jobsDirty && !$("#jobsView").classList.contains("hidden")) loadJobs();
}

/* ------------------------------------------------------------------ */
/* Settings drawer                                                     */
/* ------------------------------------------------------------------ */
async function openDrawer() {
  $("#settingsDrawer").classList.remove("hidden");
  await Promise.all([loadDrawerProfile(), loadApplyProfile(), loadCompanies()]);
}
function closeDrawer() {
  $("#settingsDrawer").classList.add("hidden");
}

function joinList(arr) { return (arr || []).join(", "); }
function splitList(str) { return str.split(",").map((s) => s.trim()).filter(Boolean); }

async function loadDrawerProfile() {
  const p = state.profile || (await apiFetch("/profile"));
  state.profile = p;
  $("#profileSeniority").value = p.seniority || "";
  $("#searchTitles").value = joinList(p.titles);
  $("#searchKeywords").value = joinList(p.keywords);
  $("#searchSkills").value = joinList(p.skills);
  $("#searchIndustries").value = joinList(p.industries);
  $("#searchLocations").value = joinList(p.locations);
  $("#searchExclude").value = joinList(p.exclude_keywords);
  $("#profileSummary").value = p.summary || "";
  const strictness = p.match_strictness || 5;
  $("#matchStrictness").value = strictness;
  $("#strictnessValLabel").textContent = strictness;
  $("#resumeStatus").textContent = p.resume_filename ? `Resume on file (uploaded ${p.resume_uploaded_at ? new Date(p.resume_uploaded_at).toLocaleDateString() : ""})` : "No resume uploaded.";
  $("#removeResumeBtn").classList.toggle("hidden", !p.resume_filename);
}

async function saveProfile() {
  try {
    await apiFetch("/profile", {
      method: "PUT",
      body: JSON.stringify({
        titles: splitList($("#searchTitles").value),
        keywords: splitList($("#searchKeywords").value),
        locations: splitList($("#searchLocations").value),
        skills: splitList($("#searchSkills").value),
        industries: splitList($("#searchIndustries").value),
        seniority: $("#profileSeniority").value || null,
        exclude_keywords: splitList($("#searchExclude").value),
        summary: $("#profileSummary").value || null,
        match_strictness: Number($("#matchStrictness").value),
      }),
    });
    toast("Profile saved");
    await loadProfileState();
  } catch (e) { toast(e.message, true); }
}

async function loadApplyProfile() {
  const ap = await apiFetch("/profile/apply");
  state.applyProfile = ap;
  $("#applyFullName").value = ap.identity.full_name || "";
  $("#applyEmail").value = ap.identity.email || "";
  $("#applyPhone").value = ap.identity.phone || "";
  $("#applyLinkedin").value = ap.identity.linkedin_url || "";
  $("#applyLocation").value = ap.identity.location || "";
  $("#applyWorkAuth").value = ap.identity.work_authorization || "";
  $("#applySponsorship").checked = !!ap.identity.requires_sponsorship;
  $("#applyAutoEnabled").checked = !!ap.settings.auto_apply_enabled;
  $("#applyMinConfidence").value = ap.settings.min_auto_confidence;
  $("#applyAlwaysConfirm").checked = !!ap.settings.always_confirm_submit;
}

async function saveApplyProfile() {
  try {
    await apiFetch("/profile/apply", {
      method: "PUT",
      body: JSON.stringify({
        identity: {
          full_name: $("#applyFullName").value,
          email: $("#applyEmail").value,
          phone: $("#applyPhone").value,
          linkedin_url: $("#applyLinkedin").value,
          location: $("#applyLocation").value,
          work_authorization: $("#applyWorkAuth").value,
          requires_sponsorship: $("#applySponsorship").checked,
        },
        settings: {
          auto_apply_enabled: $("#applyAutoEnabled").checked,
          min_auto_confidence: Number($("#applyMinConfidence").value),
          always_confirm_submit: $("#applyAlwaysConfirm").checked,
        },
      }),
    });
    toast("Apply profile saved");
    await loadApplyProfile();
  } catch (e) { toast(e.message, true); }
}

async function loadCompanies() {
  const companies = await apiFetch("/companies");
  $("#companyList").innerHTML = companies.map((c) =>
    `<div class="company-item"><span>${esc(c.name)} <span class="muted small">(${esc(c.ats_type)})</span></span>
     <button class="link-btn" data-company-id="${c.id}">Remove</button></div>`
  ).join("") || `<p class="muted small">No target companies yet.</p>`;
  $$("#companyList [data-company-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try { await apiFetch(`/companies/${btn.dataset.companyId}`, { method: "DELETE" }); loadCompanies(); }
      catch (e) { toast(e.message, true); }
    });
  });
}

/* ------------------------------------------------------------------ */
/* Resume upload                                                       */
/* ------------------------------------------------------------------ */
async function uploadResume(fileInput, statusEl) {
  const file = fileInput.files[0];
  if (!file) return;
  if (statusEl) statusEl.textContent = "Uploading and analyzing…";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await apiFetch("/profile/resume", { method: "POST", body: fd });
    if (statusEl) statusEl.textContent = res.message || "Resume uploaded.";
    toast("Resume digested");
    await loadProfileState();
    // refresh drawer fields if open
    if (!$("#settingsDrawer").classList.contains("hidden")) loadDrawerProfile();
    // update profile card in gate list
    const me = state.users.find((u) => u.id === state.userId);
    if (me) me.has_resume = true;
    postResumeDigest(res);
  } catch (e) {
    if (statusEl) statusEl.textContent = e.message;
    toast(e.message, true);
  }
}

/* ------------------------------------------------------------------ */
/* Profile switcher menu                                               */
/* ------------------------------------------------------------------ */
function toggleProfileMenu() {
  const menu = $("#profileMenu");
  if (!menu.classList.contains("hidden")) { menu.classList.add("hidden"); return; }
  menu.innerHTML = state.users.map((u) =>
    `<button class="menu-item ${u.id === state.userId ? "active" : ""}" data-uid="${u.id}">${esc(u.name)}</button>`
  ).join("") + `<button class="menu-item add" data-uid="new">+ New profile</button>`;
  menu.classList.remove("hidden");
  menu.querySelectorAll(".menu-item").forEach((item) => {
    item.addEventListener("click", async () => {
      menu.classList.add("hidden");
      if (item.dataset.uid === "new") {
        showGate();
      } else {
        const id = Number(item.dataset.uid);
        if (id !== state.userId) {
          setUserId(id);
          $("#chatMessages").innerHTML = "";
          await boot();
        }
      }
    });
  });
}

/* ------------------------------------------------------------------ */
/* Static event wiring                                                 */
/* ------------------------------------------------------------------ */
function wireStaticHandlers() {
  // Gate
  $("#createProfileForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#newProfileName").value.trim();
    if (!name) return;
    try { await createProfile(name); $("#newProfileName").value = ""; $("#gateMessage").textContent = ""; }
    catch (err) { $("#gateMessage").textContent = err.message; }
  });

  // Tabs
  $$(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));

  // Profile switch
  $("#profileSwitchBtn").addEventListener("click", (e) => { e.stopPropagation(); toggleProfileMenu(); });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".profile-switch")) $("#profileMenu").classList.add("hidden");
  });

  // Settings drawer
  $("#settingsBtn").addEventListener("click", openDrawer);
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#settingsDrawer").addEventListener("click", (e) => { if (e.target.id === "settingsDrawer") closeDrawer(); });

  // Chat
  $("#chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#chatInput").value.trim();
    if (!text) return;
    $("#chatInput").value = "";
    autoGrow($("#chatInput"));
    sendChat(text);
  });
  $("#chatInput").addEventListener("input", (e) => autoGrow(e.target));
  $("#chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); }
  });
  $$("#promptChips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const p = chip.dataset.prompt;
      if (p.endsWith(" ")) { $("#chatInput").value = p; $("#chatInput").focus(); autoGrow($("#chatInput")); }
      else sendChat(p);
    });
  });

  // Jobs view
  $("#jobsFilter").addEventListener("input", renderJobs);
  $("#jobsStatusFilter").addEventListener("change", loadJobs);

  // Job modal
  $("#jobModalClose").addEventListener("click", closeJobModal);
  $("#jobModal").addEventListener("click", (e) => { if (e.target.id === "jobModal") closeJobModal(); });

  // Resume uploads
  $("#chatResumeFile").addEventListener("change", (e) => uploadResume(e.target, $("#chatResumeStatus")));
  $("#resumeFile").addEventListener("change", (e) => uploadResume(e.target, $("#resumeStatus")));
  $("#removeResumeBtn").addEventListener("click", async () => {
    if (!confirm("Remove resume?")) return;
    try { await apiFetch("/profile/resume", { method: "DELETE" }); toast("Resume removed"); await loadProfileState(); loadDrawerProfile(); }
    catch (e) { toast(e.message, true); }
  });

  // Drawer actions
  $("#matchStrictness").addEventListener("input", (e) => { $("#strictnessValLabel").textContent = e.target.value; });
  $("#saveProfileBtn").addEventListener("click", saveProfile);
  $("#saveApplyProfileBtn").addEventListener("click", saveApplyProfile);
  $("#addCompanyBtn").addEventListener("click", async () => {
    const name = $("#companyName").value.trim();
    const url = $("#companyUrl").value.trim();
    if (!name || !url) { toast("Name and URL required", true); return; }
    try {
      await apiFetch("/companies", { method: "POST", body: JSON.stringify({ name, careers_url: url }) });
      $("#companyName").value = ""; $("#companyUrl").value = "";
      loadCompanies();
    } catch (e) { toast(e.message, true); }
  });
  $("#runCompanySearchBtn").addEventListener("click", async () => {
    toast("Searching target companies…");
    try {
      const p = state.profile || {};
      const r = await apiFetch("/agent/company-search", {
        method: "POST",
        body: JSON.stringify({
          titles: p.titles, keywords: p.keywords, locations: p.locations,
          skills: p.skills, exclude_keywords: p.exclude_keywords, seniority: p.seniority,
        }),
      });
      toast(r.message);
      state.jobsDirty = true;
    } catch (e) { toast(e.message, true); }
  });
  $("#addJobBtn").addEventListener("click", async () => {
    const title = $("#manualTitle").value.trim();
    const company = $("#manualCompany").value.trim();
    const url = $("#manualUrl").value.trim();
    if (!title || !company || !url) { $("#manualJobMessage").textContent = "Title, company, and URL required."; return; }
    try {
      await apiFetch("/jobs", {
        method: "POST",
        body: JSON.stringify({ title, company, location: $("#manualLocation").value.trim() || null, url }),
      });
      $("#manualTitle").value = ""; $("#manualCompany").value = ""; $("#manualLocation").value = ""; $("#manualUrl").value = "";
      $("#manualJobMessage").textContent = "Job added.";
      toast("Job added");
      state.jobsDirty = true;
    } catch (e) { $("#manualJobMessage").textContent = e.message; }
  });
  $("#deleteAllJobsBtn").addEventListener("click", async () => {
    if (!confirm("Delete ALL jobs for this profile? This cannot be undone.")) return;
    try { const r = await apiFetch("/jobs", { method: "DELETE" }); toast(`Deleted ${r.deleted} jobs`); state.jobsDirty = true; loadJobs(); }
    catch (e) { toast(e.message, true); }
  });

  // Esc closes overlays
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!$("#jobModal").classList.contains("hidden")) closeJobModal();
      else if (!$("#settingsDrawer").classList.contains("hidden")) closeDrawer();
    }
  });
}

function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

document.addEventListener("DOMContentLoaded", init);
