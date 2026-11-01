// US15 #44: plan a trip backward from the desired arrival time.
(function () {
  "use strict";

  const panel = document.getElementById("leave-by-panel");
  const form = document.getElementById("leave-by-form");
  const dayInput = document.getElementById("leave-by-day");
  const arriveInput = document.getElementById("leave-by-arrive");
  const status = document.getElementById("leave-by-status");
  const result = document.getElementById("leave-by-result");
  const leaveTime = document.getElementById("leave-by-time");
  const duration = document.getElementById("leave-by-duration");
  const fare = document.getElementById("leave-by-fare");
  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  let pickup = null;
  let dropoff = null;
  let sequence = 0;

  // US17: tell save-plan.js which plan the shown result belongs to.
  function announce(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function clearResult() {
    result.hidden = true;
    status.textContent = "";
    announce("taxiscope:plan-cleared", { mode: "arrive_by" });
  }

  document.addEventListener("taxiscope:map-ready", (event) => {
    dayInput.value = String(event.detail.data.day);
    arriveInput.value = `${String(event.detail.data.hour).padStart(2, "0")}:00`;
  });

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickup = event.detail.pickup;
    dropoff = event.detail.dropoff;
    panel.hidden = pickup === null || dropoff === null;
    sequence += 1;
    clearResult();
  });

  for (const [field, eventName] of [[dayInput, "change"], [arriveInput, "input"]]) {
    field.addEventListener(eventName, () => {
      sequence += 1;
      clearResult();
    });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (panel.hidden || !form.checkValidity()) return;
    const request = ++sequence;
    const params = new URLSearchParams({
      from: pickup,
      to: dropoff,
      day: dayInput.value,
      arrive: arriveInput.value,
    });
    result.hidden = true;
    status.textContent = "Calculating...";
    fetch(`/api/routes/leave-by?${params}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (request !== sequence) return;
        announce("taxiscope:plan-result", {
          mode: "arrive_by", day: Number(params.get("day")), time: params.get("arrive"),
        });
        if (!data.enough_data) {
          status.textContent = "Not enough data";
          return;
        }
        leaveTime.textContent = `${DAYS[data.leave_day]} ${data.leave}`;
        duration.textContent = `${Number(data.avg_duration_min).toFixed(1)} min`;
        fare.textContent = `$${Number(data.fare_avg).toFixed(2)}`;
        result.hidden = false;
        status.textContent = "";
      })
      .catch(() => {
        if (request !== sequence) return;
        status.textContent = "Could not load leave-by estimate";
      });
  });
})();
