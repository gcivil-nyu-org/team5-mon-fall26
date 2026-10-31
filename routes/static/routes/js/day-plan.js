// US20 #49: build a multi-stop day plan from map clicks, then save it.
(function () {
  "use strict";

  const MAX_STOPS = 10;
  const MIN_STOPS = 3;
  const QUARTER_HOUR = /^([01]\d|2[0-3]):(00|15|30|45)$/;
  const panel = document.getElementById("day-plan-panel");
  const signin = document.getElementById("day-plan-signin");
  const addButton = document.getElementById("day-plan-add");
  const list = document.getElementById("day-plan-stops");
  const form = document.getElementById("day-plan-form");
  const daySelect = document.getElementById("day-plan-day");
  const nameInput = document.getElementById("day-plan-name");
  const saveButton = document.getElementById("day-plan-save");
  const clearButton = document.getElementById("day-plan-clear");
  const status = document.getElementById("day-plan-status");
  const openLink = document.getElementById("day-plan-open");
  const zoneNames = new Map();
  let selection = { pickup: null, dropoff: null };
  let mapHour = 8;
  // The plan being built: [{ zone, leave: "HH:MM" or "" for the last stop }].
  let stops = [];
  let saving = false;

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  // One hour after a "HH:MM" leave time, at most 23:45.
  function hourLater(leave) {
    const [hour, minute] = leave.split(":").map(Number);
    const minutes = Math.min(hour * 60 + minute + 60, 23 * 60 + 45);
    return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
  }

  // Every stop but the last needs a leave time; fill new gaps with defaults.
  function fillLeaveTimes() {
    stops.forEach((stop, i) => {
      if (i === stops.length - 1) {
        stop.leave = "";
      } else if (stop.leave === "") {
        stop.leave = i === 0 || !QUARTER_HOUR.test(stops[i - 1].leave)
          ? `${pad(mapHour)}:00`
          : hourLater(stops[i - 1].leave);
      }
    });
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle("error", isError);
  }

  function canSave() {
    return (
      !saving &&
      stops.length >= MIN_STOPS &&
      stops.length <= MAX_STOPS &&
      stops.slice(0, -1).every((stop) => QUARTER_HOUR.test(stop.leave)) &&
      nameInput.value.trim() !== ""
    );
  }

  function updateControls() {
    const bothZones = selection.pickup !== null && selection.dropoff !== null;
    const justSaved = openLink !== null && !openLink.hidden;
    panel.hidden = !bothZones && stops.length === 0 && !justSaved;
    if (!form) {
      signin.hidden = !bothZones;
      return;
    }
    addButton.hidden = !bothZones;
    form.hidden = stops.length === 0;
    saveButton.disabled = !canSave();
  }

  function stopItem(stop, i) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = zoneNames.get(stop.zone) ?? `Zone ${stop.zone}`;
    item.append(label);
    if (i < stops.length - 1) {
      const time = document.createElement("input");
      time.type = "time";
      time.step = "900";
      time.required = true;
      time.value = stop.leave;
      time.setAttribute("aria-label", `Leave ${label.textContent} at`);
      time.addEventListener("input", () => {
        stop.leave = time.value;
        updateControls();
      });
      item.append(time);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "day-plan-remove";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${label.textContent}`);
    remove.addEventListener("click", () => removeStop(i));
    item.append(remove);
    return item;
  }

  function render() {
    list.replaceChildren(...stops.map(stopItem));
    updateControls();
  }

  // The same rule as a saved plan: the removed stop's time goes with it and
  // the stop before keeps its own; a new last stop has no leave time.
  function removeStop(i) {
    stops.splice(i, 1);
    fillLeaveTimes();
    showStatus("");
    render();
  }

  function addToPlan() {
    const { pickup, dropoff } = selection;
    if (pickup === null || dropoff === null) return;
    const added = stops.length > 0 && stops.at(-1).zone === pickup ? [dropoff] : [pickup, dropoff];
    if (stops.length + added.length > MAX_STOPS) {
      showStatus(`A day plan can have at most ${MAX_STOPS} stops.`, true);
      return;
    }
    stops.push(...added.map((zone) => ({ zone, leave: "" })));
    fillLeaveTimes();
    openLink.hidden = true;
    showStatus(stops.length < MIN_STOPS ? "Select the next stop on the map." : "");
    render();
    // The last stop becomes the next pickup, so the next stop is one click away.
    document.dispatchEvent(
      new CustomEvent("taxiscope:select-route", {
        detail: { pickup: stops.at(-1).zone, dropoff: null },
      })
    );
  }

  document.addEventListener("taxiscope:map-ready", (event) => {
    for (const feature of event.detail.data.features) {
      const props = feature.properties;
      zoneNames.set(props.zone_id, props.name);
    }
    mapHour = event.detail.data.hour;
    if (daySelect) daySelect.value = String(event.detail.data.day);
  });

  document.addEventListener("taxiscope:time-changed", (event) => {
    mapHour = event.detail.hour;
  });

  document.addEventListener("taxiscope:zones-selected", (event) => {
    selection = { pickup: event.detail.pickup, dropoff: event.detail.dropoff };
    updateControls();
  });

  if (!form) return; // guests see "Sign in to plan a day" instead

  addButton.addEventListener("click", addToPlan);
  nameInput.addEventListener("input", updateControls);
  clearButton.addEventListener("click", () => {
    stops = [];
    showStatus("");
    render();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!canSave()) return;
    const submittedName = nameInput.value.trim();
    saving = true;
    updateControls();
    showStatus("Saving day plan…");
    const body = new URLSearchParams({
      name: submittedName,
      day_of_week: daySelect.value,
      stops: stops.map((stop) => stop.zone).join(","),
      leave_times: stops.slice(0, -1).map((stop) => stop.leave).join(","),
    });
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
        body,
      });
      if (response.status === 401) throw new Error("Sign in to save day plans.");
      if (response.status === 403) {
        throw new Error("Your session has changed. Reload the page and try again.");
      }
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.errors
          ? Object.values(result.errors).flat().join(" ")
          : "Could not save this day plan. Please try again.");
      }
      stops = [];
      nameInput.value = "";
      showStatus(`Saved “${result.name}” to My day plans.`);
      openLink.href = result.url;
      openLink.hidden = false;
    } catch (error) {
      showStatus(error.message === "Failed to fetch"
        ? "Could not save this day plan. Check your connection and try again."
        : error.message, true);
    } finally {
      saving = false;
      render();
    }
  });
})();
