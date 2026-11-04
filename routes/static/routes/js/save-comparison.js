// US23 #70: save the two zones on the compare page (like save-route.js, US13).
(function () {
  "use strict";

  const panel = document.getElementById("save-comparison-panel");
  const form = document.getElementById("save-comparison-form");
  const status = document.getElementById("save-comparison-status");
  const signin = document.getElementById("save-comparison-signin");
  const button = document.getElementById("save-comparison-button");
  const name = document.getElementById("comparison-name");
  const signinUrl = signin.getAttribute("href");
  let selection = { a: null, b: null };
  let revision = 0;
  let saving = false;

  // Sent by compare.js after every change, with the page's current address.
  document.addEventListener("taxiscope:compare-changed", (event) => {
    selection = { a: event.detail.a, b: event.detail.b };
    revision += 1;
    panel.hidden = selection.a == null || selection.b == null;
    status.textContent = "";
    status.classList.remove("error");
    // After signing in, come back to this comparison.
    signin.setAttribute("href", `${signinUrl}?next=${encodeURIComponent(event.detail.address)}`);
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
    status.textContent = "Saving comparison…";
    const body = new URLSearchParams({
      name: submittedName,
      zone_a: selection.a,
      zone_b: selection.b,
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
          : "Could not save this comparison. Please try again.");
      }
      status.textContent = `Saved “${result.name}”.`;
      if (name.value === submittedName) name.value = "";
    } catch (error) {
      if (submittedRevision !== revision) return;
      status.classList.add("error");
      status.textContent = error.message === "Failed to fetch"
        ? "Could not save this comparison. Check your connection and try again."
        : error.message;
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
})();
