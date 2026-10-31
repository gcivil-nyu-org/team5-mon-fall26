// US17 #46: save the "Leave by" plan behind the result currently shown.
(function () {
  "use strict";

  const panel = document.getElementById("save-plan-panel");
  const form = document.getElementById("save-plan-form");
  const status = document.getElementById("save-plan-status");
  const button = document.getElementById("save-plan-button");
  const name = document.getElementById("plan-name");
  let zones = { pickup: null, dropoff: null };
  let plan = null; // { mode, day, time } of the result on screen
  let revision = 0;
  let saving = false;

  function reset() {
    plan = null;
    revision += 1;
    panel.hidden = true;
    status.textContent = "";
    status.classList.remove("error");
  }

  document.addEventListener("taxiscope:zones-selected", (event) => {
    zones = { pickup: event.detail.pickup, dropoff: event.detail.dropoff };
    reset();
  });

  document.addEventListener("taxiscope:plan-cleared", reset);

  document.addEventListener("taxiscope:plan-result", (event) => {
    if (zones.pickup == null || zones.dropoff == null) return;
    plan = event.detail;
    revision += 1;
    panel.hidden = false;
    status.textContent = "";
    status.classList.remove("error");
  });

  if (!form) return; // guests see a sign-in link instead
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || !plan || panel.hidden) return;
    const submittedRevision = revision;
    const submittedName = name.value;
    saving = true;
    button.disabled = true;
    status.classList.remove("error");
    status.textContent = "Saving plan…";
    const body = new URLSearchParams({
      name: submittedName,
      pickup_zone: zones.pickup,
      dropoff_zone: zones.dropoff,
      mode: plan.mode,
      day_of_week: plan.day,
      time: plan.time,
    });
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
        body,
      });
      if (submittedRevision !== revision) return;
      if (response.status === 401 || response.status === 403) {
        throw new Error("Your session has changed. Reload the page and try again.");
      }
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.errors
          ? Object.values(result.errors).flat().join(" ")
          : "Could not save this plan. Please try again.");
      }
      status.textContent = `Saved “${result.name}” to My plans.`;
      if (name.value === submittedName) name.value = "";
    } catch (error) {
      if (submittedRevision !== revision) return;
      status.classList.add("error");
      status.textContent = error.message === "Failed to fetch"
        ? "Could not save this plan. Check your connection and try again."
        : error.message;
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
})();
