const DEFAULT_API = "http://127.0.0.1:8000";

async function getApiBase() {
  const stored = await chrome.storage.sync.get(["apiBase"]);
  return stored.apiBase || DEFAULT_API;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "fetchFillPayload") {
    (async () => {
      try {
        const apiBase = await getApiBase();
        let jobId = message.jobId;

        if (!jobId && message.url) {
          const matchRes = await fetch(
            `${apiBase}/api/apply/match?url=${encodeURIComponent(message.url)}`
          );
          if (matchRes.ok) {
            const match = await matchRes.json();
            if (match.matched) {
              jobId = match.job_id;
            }
          }
        }

        if (!jobId) {
          sendResponse({ ok: false, error: "No matching job in Career Agent for this page." });
          return;
        }

        const res = await fetch(`${apiBase}/api/jobs/${jobId}/apply/fill-payload`);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          sendResponse({ ok: false, error: err.detail || "Failed to load fill payload." });
          return;
        }

        const payload = await res.json();
        sendResponse({ ok: true, payload, apiBase });
      } catch (error) {
        sendResponse({ ok: false, error: String(error) });
      }
    })();
    return true;
  }
});
