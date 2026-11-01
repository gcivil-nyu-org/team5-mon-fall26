// US19 #48: adjacent pickup zones where the selected trip is historically cheaper.
(function () {
  "use strict";

  const panel = document.getElementById("nearby-panel");
  const status = document.getElementById("nearby-status");
  const list = document.getElementById("nearby-list");
  let pickup = null;
  let dropoff = null;
  let day = null;
  let hour = null;
  // Only the newest request may write the section.
  let sequence = 0;

  function money(value) {
    return `$${Number(value).toFixed(2)}`;
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle("error", isError);
  }

  function suggestionButton(suggestion, routeDropoff) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nearby-zone";
    button.textContent =
      `${suggestion.name}: ${money(suggestion.fare_avg)}, save ${money(suggestion.saving)}, ` +
      `${Number(suggestion.avg_duration_min).toFixed(1)} min`;
    button.setAttribute("aria-label", `Use ${suggestion.name} as the pickup: ${button.textContent}`);
    button.addEventListener("click", () => {
      document.dispatchEvent(
        new CustomEvent("taxiscope:select-route", {
          detail: { pickup: suggestion.zone_id, dropoff: routeDropoff },
        })
      );
    });
    item.append(button);
    return item;
  }

  function show(data) {
    list.replaceChildren();
    // An island can never get a suggestion, so say that before "not enough data".
    if (data.neighbor_count === 0) {
      showStatus("No zones border this pickup zone.");
    } else if (!data.enough_data) {
      showStatus("Not enough past trips on this route to compare nearby zones.");
    } else if (data.suggestions.length === 0) {
      showStatus("No adjacent pickup zone is cheaper at this time.");
    } else {
      showStatus("");
      for (const suggestion of data.suggestions) {
        list.append(suggestionButton(suggestion, data.to));
      }
    }
  }

  function load() {
    const request = ++sequence;
    // A trip within one zone has no sensible nearby pickup.
    if (pickup === null || dropoff === null || pickup === dropoff || day === null) {
      panel.hidden = true;
      list.replaceChildren();
      showStatus("");
      return;
    }

    panel.hidden = false;
    list.replaceChildren();
    showStatus("Loading…");
    const params = new URLSearchParams({ from: pickup, to: dropoff, day, hour });
    fetch(`/api/routes/nearby?${params}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (request !== sequence) return;
        show(data);
      })
      .catch(() => {
        if (request !== sequence) return;
        showStatus("Could not load nearby pickup zones", true);
      });
  }

  document.addEventListener("taxiscope:map-ready", (event) => {
    day = event.detail.data.day;
    hour = event.detail.data.hour;
    load();
  });

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickup = event.detail.pickup;
    dropoff = event.detail.dropoff;
    load();
  });

  // Sent by filters.js once the map shows the new day and hour. Unlike the
  // best/worst windows, the comparison is for one hour, so both matter.
  document.addEventListener("taxiscope:time-changed", (event) => {
    if (event.detail.day === day && event.detail.hour === hour) return;
    day = event.detail.day;
    hour = event.detail.hour;
    load();
  });
})();
