// US8 #10: shared collapsible panel for the fare and windows components.
(function () {
  "use strict";

  const panel = document.getElementById("summary-panel");
  const toggleButton = document.getElementById("summary-toggle");
  const routeLabel = document.getElementById("summary-route");
  const timeLabel = document.getElementById("summary-time");
  let pickupZoneId = null;
  let dropoffZoneId = null;
  let day = null;
  let hour = null;
  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  function hasRoute() {
    return pickupZoneId !== null && dropoffZoneId !== null;
  }

  function setOpen(isOpen) {
    panel.hidden = !isOpen;
    toggleButton.hidden = pickupZoneId === null;
    toggleButton.setAttribute("aria-expanded", String(isOpen));
  }

  function updateRouteLabel() {
    const pickup = document.getElementById("pickup-zone").textContent;
    const dropoff = document.getElementById("dropoff-zone").textContent;
    routeLabel.textContent = hasRoute() && pickupZoneId === dropoffZoneId
      ? `${pickup} — Trips within this zone`
      : `${pickup} → ${hasRoute() ? dropoff : "all destinations"}`;
  }

  function updateTimeLabel() {
    if (pickupZoneId === null || day === null || hour === null) return;
    timeLabel.textContent = hasRoute()
      ? `Selected ${DAYS[day]} ${hour}:00–${hour}:59`
      : `Selected ${DAYS[day]} ${hour}:00–${hour}:59; all trips from this pickup zone`;
  }

  function clearSummary() {
    setOpen(false);
    routeLabel.textContent = "";
    timeLabel.textContent = "";
  }

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickupZoneId = event.detail.pickup;
    dropoffZoneId = event.detail.dropoff;

    if (pickupZoneId === null) {
      clearSummary();
      return;
    }

    updateRouteLabel();
    updateTimeLabel();
    setOpen(true);
  });

  document.addEventListener("taxiscope:map-ready", (event) => {
    day = event.detail.data.day;
    hour = event.detail.data.hour;
    updateTimeLabel();
  });
  document.addEventListener("taxiscope:time-changed", (event) => {
    day = event.detail.day;
    hour = event.detail.hour;
    updateTimeLabel();
  });
  toggleButton.addEventListener("click", () => {
    const opening = panel.hidden;
    setOpen(opening);
  });
})();
