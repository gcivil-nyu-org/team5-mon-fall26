// US26 #73: recent rider fares for the selected route in the trip summary.
(function () {
  "use strict";

  const row = document.getElementById("rider-reports-row");
  const status = document.getElementById("rider-reports-status");
  const list = document.getElementById("rider-reports-list");
  let requestSequence = 0;

  function dollars(value) {
    return "$" + Number(value).toFixed(2);
  }

  function reportLine(report) {
    const item = document.createElement("li");
    const hour = String(report.ride_hour).padStart(2, "0");
    let label = report.ride_day + " " + hour + ":00 - Taxi " + dollars(report.taxi_fare);
    if (report.rideshare_quote !== null) {
      const service = report.rideshare_service === "uber" ? "Uber" : "Lyft";
      label += "; " + service + " quote " + dollars(report.rideshare_quote);
    }
    item.textContent = label;
    return item;
  }

  document.addEventListener("taxiscope:zones-selected", (event) => {
    const sequence = ++requestSequence;
    const pickup = event.detail.pickup;
    const dropoff = event.detail.dropoff;
    row.hidden = pickup === null || dropoff === null;
    list.replaceChildren();
    status.classList.remove("error");
    if (row.hidden) {
      status.textContent = "";
      return;
    }

    status.textContent = "Loading...";
    const params = new URLSearchParams({ from: pickup, to: dropoff });
    fetch("/api/routes/reports?" + params)
      .then((response) => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then((data) => {
        if (sequence !== requestSequence) return;
        if (!data.enough_data) {
          status.textContent = "Not enough reports yet";
          return;
        }
        let summary = data.report_count + " reports; median taxi fare " +
          dollars(data.median_taxi_fare);
        if (data.rideshare_quote_count > 0) {
          summary += "; " + data.rideshare_quote_count + " rideshare quotes; median " +
            dollars(data.median_rideshare_quote);
        }
        status.textContent = summary;
        data.recent_reports.forEach((report) => list.appendChild(reportLine(report)));
      })
      .catch((error) => {
        if (sequence !== requestSequence) return;
        console.error("Rider reports error:", error);
        status.textContent = "Could not load rider reports";
        status.classList.add("error");
      });
  });
})();
