const apiInput = document.getElementById("apiBase");
const status = document.getElementById("status");

async function testConnection(apiBase) {
  const res = await fetch(`${apiBase}/api/health`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (data.status !== "ok") throw new Error("Unexpected health response");
}

chrome.storage.sync.get(["apiBase"], (stored) => {
  if (stored.apiBase) apiInput.value = stored.apiBase;
  const apiBase = (stored.apiBase || apiInput.value).trim().replace(/\/$/, "");
  testConnection(apiBase)
    .then(() => {
      status.textContent = "Connected to Career Agent.";
    })
    .catch(() => {
      status.textContent = "Start Career Agent (.\\start.ps1) then test connection.";
    });
});

document.getElementById("saveBtn").addEventListener("click", async () => {
  const apiBase = apiInput.value.trim().replace(/\/$/, "");
  await chrome.storage.sync.set({ apiBase });
  status.textContent = "Saved.";
});

document.getElementById("testBtn").addEventListener("click", async () => {
  const apiBase = apiInput.value.trim().replace(/\/$/, "");
  status.textContent = "Testing...";
  try {
    await testConnection(apiBase);
    await chrome.storage.sync.set({ apiBase });
    status.textContent = "Connected to Career Agent.";
  } catch (error) {
    status.textContent = `Cannot reach API: ${error.message}`;
  }
});
