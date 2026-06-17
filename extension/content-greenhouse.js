window.CareerAgentFillHandlers.greenhouse = function fillGreenhouse(payload) {
  const fields = payload.fields || {};
  const filled = [];
  const fill = window.CareerAgentFill.setInput.bind(window.CareerAgentFill);

  if (fill(["#first_name", 'input[name*="first_name"]'], fields.first_name)) filled.push("first_name");
  if (fill(["#last_name", 'input[name*="last_name"]'], fields.last_name)) filled.push("last_name");
  if (fill(["#email", 'input[type="email"]', 'input[name*="email"]'], fields.email)) filled.push("email");
  if (fill(["#phone", 'input[type="tel"]', 'input[name*="phone"]'], fields.phone)) filled.push("phone");
  if (
    fill(
      ["#job_application_location", 'input[name*="location"]', "#candidate-location"],
      fields.location
    )
  ) {
    filled.push("location");
  }
  if (fill(['input[name*="linkedin"]', 'input[id*="linkedin"]'], fields.linkedin_url)) filled.push("linkedin");
  if (fill(['textarea[name*="cover"]', "#cover_letter"], fields.cover_letter)) filled.push("cover_letter");

  const answers = (payload.answers || []).map((item) => ({
    question: item.question,
    answer: item.answer,
  }));
  filled.push(...window.CareerAgentFill.fillTextareas(answers));

  return filled;
};

(function initGreenhouse() {
  window.CareerAgentFill.createFillButton("greenhouse");
  const jobId = window.CareerAgentFill.getJobIdFromUrl();
  if (jobId) {
    window.CareerAgentFill.showBanner(
      "Career Agent: click 'Fill from Career Agent' to populate this application."
    );
  }
})();
