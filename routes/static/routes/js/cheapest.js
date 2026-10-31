// US16 #45: the cheapest of the next 3 one-hour slots for the selected trip.
(function () {
  "use strict";

  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const modeInputs = document.querySelectorAll('input[name="plan-mode"]');
  const arriveMode = document.getElementById("arrive-by-mode");
  const cheapestMode = document.getElementById("cheapest-mode");
  const form = document.getElementById("cheapest-form");
  const dayInput = document.getElementById("cheapest-day");
  const startInput = document.getElementById("cheapest-start");
  const nowButton = document.getElementById("cheapest-now");
  const status = document.getElementById("cheapest-status");
  const result = document.getElementById("cheapest-result");
  const tbody = document.getElementById("cheapest-hours");
  const best = document.getElementById("cheapest-best");
  const leave = document.getElementById("cheapest-leave");
  const duration = document.getElementById("cheapest-duration");
  const arrive = document.getElementById("cheapest-arrive");
  let pickup = null;
  let dropoff = null;
  let sequence = 0;

  function clearResult() {
    result.hidden = true;
    status.textContent = "";
  }

  // Current day (Monday=0) and HH:MM in New York, whatever the browser's time zone.
  function nycNow() {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "long",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date()).map((p) => [p.type, p.value])
    );
    return { day: DAYS.indexOf(parts.weekday), start: `${parts.hour}:${parts.minute}` };
  }

  function hourLabel(slot) {
    const h = String(slot.hour).padStart(2, "0");
    return `${DAYS[slot.day].slice(0, 3)} ${h}:00–${h}:59`;
  }

  function show(data) {
    tbody.replaceChildren();
    data.hours.forEach((slot, i) => {
      const row = document.createElement("tr");
      const hourCell = document.createElement("td");
      const fareCell = document.createElement("td");
      hourCell.textContent = hourLabel(slot);
      if (slot.enough_data) {
        fareCell.textContent = `$${Number(slot.fare_avg).toFixed(2)}`;
      } else {
        fareCell.textContent = "Not enough data";
        fareCell.className = "no-data";
      }
      if (i === data.cheapest) {
        row.className = "is-cheapest";
        fareCell.textContent += " (cheapest)";
      }
      row.append(hourCell, fareCell);
      tbody.append(row);
    });
    result.hidden = false;
    if (!data.enough_data) {
      best.hidden = true;
      status.textContent = "None of these 3 hours has enough past trips for this route.";
      return;
    }
    leave.textContent = `${DAYS[data.leave_day]} ${data.leave}`;
    duration.textContent = `${Number(data.avg_duration_min).toFixed(1)} min`;
    arrive.textContent = `${DAYS[data.arrive_day]} ${data.arrive}`;
    best.hidden = false;
    status.textContent = "";
  }

  function run(day, start, label) {
    if (pickup === null || dropoff === null) return;
    const request = ++sequence;
    const params = new URLSearchParams({ from: pickup, to: dropoff, day, start });
    result.hidden = true;
    status.textContent = "Calculating...";
    fetch(`/api/routes/cheapest?${params}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (request !== sequence) return;
        show(data);
        if (label && data.enough_data) status.textContent = label;
        document.dispatchEvent(
          new CustomEvent("taxiscope:plan-result", {
            detail: { mode: "cheapest", day: Number(day), time: start, enough_data: data.enough_data },
          })
        );
      })
      .catch(() => {
        if (request !== sequence) return;
        status.textContent = "Could not load the cheapest hour";
      });
  }

  modeInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const cheapest = input.value === "cheapest" && input.checked;
      cheapestMode.hidden = !cheapest;
      arriveMode.hidden = cheapest;
    });
  });

  document.addEventListener("taxiscope:map-ready", (event) => {
    dayInput.value = String(event.detail.data.day);
    startInput.value = `${String(event.detail.data.hour).padStart(2, "0")}:00`;
  });

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickup = event.detail.pickup;
    dropoff = event.detail.dropoff;
    sequence += 1;
    clearResult();
  });

  for (const [field, eventName] of [[dayInput, "change"], [startInput, "input"]]) {
    field.addEventListener(eventName, () => {
      sequence += 1;
      clearResult();
    });
  }

  nowButton.addEventListener("click", () => {
    const now = nycNow();
    run(now.day, now.start, `Starting now: ${DAYS[now.day]} ${now.start} (New York time)`);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.checkValidity()) return;
    run(dayInput.value, startInput.value);
  });
})();
