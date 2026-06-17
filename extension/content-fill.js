window.CareerAgentFill = {
  getJobIdFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("career_agent_job");
    if (fromQuery) return Number(fromQuery);
    const hashMatch = window.location.hash.match(/career_agent_job=(\d+)/);
    return hashMatch ? Number(hashMatch[1]) : null;
  },

  setInput(selectors, value) {
    if (!value) return false;
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (!el) continue;
      el.focus();
      el.value = value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    return false;
  },

  keywordOverlap(a, b) {
    const words = (text) =>
      new Set(
        text
          .toLowerCase()
          .split(/\W+/)
          .filter((word) => word.length > 3)
      );
    const aWords = words(a);
    const bWords = words(b);
    for (const word of aWords) {
      if (bWords.has(word)) return true;
    }
    return false;
  },

  fillTextareas(answers) {
    const filled = [];
    document.querySelectorAll("textarea").forEach((textarea, index) => {
      let label = "";
      if (textarea.id) {
        const labelEl = document.querySelector(`label[for="${textarea.id}"]`);
        if (labelEl) label = labelEl.textContent || "";
      }
      if (!label) label = textarea.getAttribute("aria-label") || textarea.placeholder || "";
      const lowerLabel = label.toLowerCase();
      for (const item of answers) {
        const question = item.question.toLowerCase();
        if (
          lowerLabel.includes(question) ||
          question.includes(lowerLabel) ||
          this.keywordOverlap(question, lowerLabel)
        ) {
          textarea.value = item.answer;
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          textarea.dispatchEvent(new Event("change", { bubbles: true }));
          filled.push(label || `textarea_${index}`);
          break;
        }
      }
    });
    return filled;
  },

  showBanner(message, type = "info") {
    const existing = document.getElementById("career-agent-banner");
    if (existing) existing.remove();

    const banner = document.createElement("div");
    banner.id = "career-agent-banner";
    banner.textContent = message;
    Object.assign(banner.style, {
      position: "fixed",
      bottom: "20px",
      right: "20px",
      zIndex: "2147483647",
      padding: "12px 16px",
      borderRadius: "12px",
      fontFamily: "system-ui, sans-serif",
      fontSize: "14px",
      maxWidth: "360px",
      boxShadow: "0 8px 24px rgba(0,0,0,0.2)",
      color: type === "error" ? "#fff" : "#0f172a",
      background: type === "error" ? "#dc2626" : "#dbeafe",
      border: "1px solid #93c5fd",
    });
    document.body.appendChild(banner);
    setTimeout(() => banner.remove(), 8000);
  },

  createFillButton(atsType) {
    if (document.getElementById("career-agent-fill-btn")) return;

    const button = document.createElement("button");
    button.id = "career-agent-fill-btn";
    button.textContent = "Fill from Career Agent";
    Object.assign(button.style, {
      position: "fixed",
      bottom: "20px",
      left: "20px",
      zIndex: "2147483647",
      padding: "12px 16px",
      borderRadius: "12px",
      border: "none",
      background: "#4f46e5",
      color: "#fff",
      fontWeight: "600",
      cursor: "pointer",
      boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
    });

    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Filling...";
      try {
        const jobId = this.getJobIdFromUrl();
        const response = await chrome.runtime.sendMessage({
          type: "fetchFillPayload",
          jobId,
          url: window.location.href,
        });
        if (!response.ok) {
          this.showBanner(response.error, "error");
          return;
        }
        const filled = window.CareerAgentFillHandlers[atsType](response.payload);
        this.showBanner(
          filled.length
            ? `Filled ${filled.length} field(s): ${filled.join(", ")}. Review and submit manually.`
            : "No fields matched. Complete the form manually.",
          filled.length ? "info" : "error"
        );
      } catch (error) {
        this.showBanner(String(error), "error");
      } finally {
        button.disabled = false;
        button.textContent = "Fill from Career Agent";
      }
    });

    document.body.appendChild(button);
  },
};

window.CareerAgentFillHandlers = {};
