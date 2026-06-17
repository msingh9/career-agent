window.CareerAgentFillHandlers.lever = function fillLever(payload) {
  const fields = payload.fields || {};
  const filled = [];
  const fill = window.CareerAgentFill.setInput.bind(window.CareerAgentFill);

  if (fill(['input[name="name"]', "#name"], fields.full_name)) filled.push("name");
  if (fill(['input[name="email"]', 'input[type="email"]'], fields.email)) filled.push("email");
  if (fill(['input[name="phone"]', 'input[type="tel"]'], fields.phone)) filled.push("phone");
  if (fill(['input[name="urls[LinkedIn]"]', 'input[name*="linkedin" i]'], fields.linkedin_url)) {
    filled.push("linkedin");
  }
  if (fill(['textarea[name="comments"]', "textarea"], fields.cover_letter)) filled.push("cover_letter");

  const answers = (payload.answers || []).map((item) => ({
    question: item.question,
    answer: item.answer,
  }));
  filled.push(...window.CareerAgentFill.fillTextareas(answers));

  return filled;
};

(function initLever() {
  window.CareerAgentFill.createFillButton("lever");
  const jobId = window.CareerAgentFill.getJobIdFromUrl();
  if (jobId) {
    window.CareerAgentFill.showBanner(
      "Career Agent: click 'Fill from Career Agent' to populate this application."
    );
  }
})();
