// US13 #42: save the selected pair without disturbing the map or time filters.
(function () {
  "use strict";

  const panel = document.getElementById("save-route-panel");
  const form = document.getElementById("save-route-form");
  const status = document.getElementById("save-route-status");
  const signin = document.getElementById("save-route-signin");
  const button = document.getElementById("save-route-button");
  const name = document.getElementById("route-name");
  let selection = { pickup: null, dropoff: null };
  let revision = 0;
  let saving = false;

  document.addEventListener("taxiscope:zones-selected", (event) => {
    selection = { pickup: event.detail.pickup, dropoff: event.detail.dropoff };
    revision += 1;
    panel.hidden = selection.pickup == null || selection.dropoff == null;
    status.textContent = "";
    status.classList.remove("error");
  });

  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || panel.hidden || form.hidden) return;
    const submittedRevision = revision;
    const submittedName = name.value;
    saving = true;
    button.disabled = true;
    status.classList.remove("error");
    status.textContent = "Saving route…";
    const body = new URLSearchParams({
      name: submittedName,
      pickup_zone: selection.pickup,
      dropoff_zone: selection.dropoff,
    });
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
        },
        body,
      });
      if (response.status === 401) {
        form.hidden = true;
        signin.hidden = false;
        status.textContent = "";
        return;
      }
      if (submittedRevision !== revision) return;
      if (response.status === 403) {
        throw new Error("Your session has changed. Reload the page and try again.");
      }
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.errors
          ? Object.values(result.errors).flat().join(" ")
          : "Could not save this route. Please try again.");
      }
      status.textContent = `Saved “${result.name}”.`;
      if (name.value === submittedName) name.value = "";
    } catch (error) {
      if (submittedRevision !== revision) return;
      status.classList.add("error");
      status.textContent = error.message === "Failed to fetch"
        ? "Could not save this route. Check your connection and try again."
        : error.message;
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
})();
