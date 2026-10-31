// US20 #49: drag and drop the stops of a saved day plan (SortableJS 1.15.6,
// vendored). The up/down buttons do the same without JavaScript.
(function () {
  "use strict";

  const list = document.getElementById("day-plan-stops");
  const status = document.getElementById("day-plan-sort-status");
  if (!list || typeof Sortable === "undefined") return;

  function reloadSoon(message) {
    status.textContent = `${message} Reloading…`;
    status.classList.add("error");
    window.setTimeout(() => window.location.reload(), 1500);
  }

  Sortable.create(list, {
    handle: ".drag-handle",
    animation: 150,
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return;
      const order = Array.from(list.children, (item) => item.dataset.stopId).join(",");
      const token = document.querySelector("[name=csrfmiddlewaretoken]").value;
      status.classList.remove("error");
      status.textContent = "Saving the new order…";
      fetch(list.dataset.reorderUrl, {
        method: "POST",
        headers: { "X-CSRFToken": token },
        body: new URLSearchParams({ order }),
      })
        .then(async (response) => {
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || "Could not save the new order.");
          }
          // The page is rendered by the server: reload it to show the new legs.
          window.location.reload();
        })
        .catch((error) => {
          reloadSoon(error.message === "Failed to fetch"
            ? "Could not save the new order. Check your connection."
            : error.message);
        });
    },
  });
})();
