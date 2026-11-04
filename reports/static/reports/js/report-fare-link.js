// US24 #71: the trip summary's "Report a fare" link opens the form with the
// selected pickup and dropoff filled in. Guests get "Sign in to report a
// fare", which comes back to the same form after signing in.
(function () {
  "use strict";

  const link = document.getElementById("report-fare-link");
  if (!link) return;
  const base = link.getAttribute("href");
  const signin = link.dataset.signin;

  document.addEventListener("taxiscope:zones-selected", (event) => {
    const pickup = event.detail.pickup ?? null;
    const dropoff = event.detail.dropoff ?? null;
    link.hidden = pickup === null || dropoff === null;
    if (link.hidden) return;
    const form = `${base}?${new URLSearchParams({ from: pickup, to: dropoff })}`;
    link.setAttribute(
      "href",
      signin ? `${signin}?${new URLSearchParams({ next: form })}` : form
    );
  });
})();
