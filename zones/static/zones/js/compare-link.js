// US22 #69: the map's "Compare" link opens /compare/ with the map's day and
// hour, and the selected pickup (if any) as zone A. It only listens to the
// map's existing events, so filters.js is unchanged.
(function () {
  "use strict";

  const link = document.getElementById("compare-link");
  if (!link) return;
  const base = link.getAttribute("href");
  let time = null;
  let pickup = null;

  function update() {
    const params = new URLSearchParams();
    if (pickup !== null) params.set("a", pickup);
    if (time) {
      params.set("day", time.day);
      params.set("hour", time.hour);
    }
    const query = params.toString();
    link.setAttribute("href", query ? `${base}?${query}` : base);
  }

  document.addEventListener("taxiscope:map-ready", (event) => {
    time = { day: event.detail.data.day, hour: event.detail.data.hour };
    update();
  });

  document.addEventListener("taxiscope:time-changed", (event) => {
    time = { day: event.detail.day, hour: event.detail.hour };
    update();
  });

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickup = event.detail.pickup ?? null;
    update();
  });
})();
