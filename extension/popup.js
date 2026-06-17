const apiInput = document.getElementById("apiBase");
const status = document.getElementById("status");

chrome.storage.sync.get(["apiBase"], (stored) => {
  if (stored.apiBase) apiInput.value = stored.apiBase;
});

document.getElementById("saveBtn").addEventListener("click", async () => {
  const apiBase = apiInput.value.trim().replace(/\/$/, "");
  await chrome.storage.sync.set({ apiBase });
  status.textContent = "Saved.";
});
