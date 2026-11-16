// US31 #93: the trip summary's "Post a shared ride" link opens the form with
// the selected pickup and dropoff filled in. Guests get "Sign in to share a
// ride", which comes back to the same form after signing in. A shared ride
// needs two different zones, so a trip within one zone has no link.
(function () {
  "use strict";

  const link = document.getElementById("share-ride-link");
  if (!link) return;
  const base = link.getAttribute("href");
  const signin = link.dataset.signin;

  document.addEventListener("taxiscope:zones-selected", (event) => {
    const pickup = event.detail.pickup ?? null;
    const dropoff = event.detail.dropoff ?? null;
    link.hidden = pickup === null || dropoff === null || pickup === dropoff;
    if (link.hidden) return;
    const form = `${base}?${new URLSearchParams({ from: pickup, to: dropoff })}`;
    link.setAttribute(
      "href",
      signin ? `${signin}?${new URLSearchParams({ next: form })}` : form
    );
  });
})();
