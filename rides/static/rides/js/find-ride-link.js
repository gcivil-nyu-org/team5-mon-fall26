// US32 #94: the trip summary's "Find a shared ride" link opens the search
// with the selected pickup, dropoff and day filled in (the page turns the
// day into the next date on that weekday). Guests get "Sign in to find a
// shared ride", which comes back to the same search after signing in. Ride
// posts always join two different zones, so a trip within one zone has no link.
(function () {
  "use strict";

  const link = document.getElementById("find-ride-link");
  if (!link) return;
  const base = link.getAttribute("href");
  const signin = link.dataset.signin;
  let pickup = null;
  let dropoff = null;
  let day = null;

  function update() {
    link.hidden = pickup === null || dropoff === null || pickup === dropoff;
    if (link.hidden) return;
    const params = { from: pickup, to: dropoff };
    if (day !== null) params.day = day;
    const search = `${base}?${new URLSearchParams(params)}`;
    link.setAttribute(
      "href",
      signin ? `${signin}?${new URLSearchParams({ next: search })}` : search
    );
  }

  document.addEventListener("taxiscope:zones-selected", (event) => {
    pickup = event.detail.pickup ?? null;
    dropoff = event.detail.dropoff ?? null;
    update();
  });

  document.addEventListener("taxiscope:time-changed", (event) => {
    day = event.detail.day ?? null;
    update();
  });
})();
