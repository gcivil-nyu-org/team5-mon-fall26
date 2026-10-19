// US1 #3: NYC taxi zones colored by trip volume, from GET /api/zones.
const map = L.map("map").setView([40.7128, -74.006], 11);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 19,
  referrerPolicy: "strict-origin-when-cross-origin",
}).addTo(map);

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const NO_TRIPS_COLOR = "#d9d9d9";
// Light to dark: quiet to busy.
const COLORS = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"];

// Split the non-zero trip counts into equal-sized groups (quantiles),
// so each color covers about the same number of zones.
function computeBreaks(counts) {
  const sorted = counts.filter((c) => c > 0).sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  const breaks = [];
  for (let i = 1; i < COLORS.length; i++) {
    breaks.push(sorted[Math.floor((i * sorted.length) / COLORS.length)]);
  }
  return [...new Set(breaks)]; // drop duplicates when many zones share a count
}

function colorFor(count, breaks) {
  if (count === 0) return NO_TRIPS_COLOR;
  let i = 0;
  while (i < breaks.length && count >= breaks[i]) i++;
  return COLORS[i];
}

function addLegend(breaks, day, hour) {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div", "legend");
    const rows = [`<strong>Total pickups</strong>`, `<small>${DAYS[day]}s, ${hour}:00–${hour}:59</small>`];
    const bounds = [1, ...breaks];
    bounds.forEach((low, i) => {
      const high = i + 1 < bounds.length ? bounds[i + 1] - 1 : null;
      const label = high === null ? `${low.toLocaleString()}+` : `${low.toLocaleString()}–${high.toLocaleString()}`;
      rows.push(`<i style="background:${COLORS[i]}"></i> ${label}`);
    });
    rows.push(`<i style="background:${NO_TRIPS_COLOR}"></i> No trips`);
    div.innerHTML = rows.join("<br>");
    return div;
  };
  legend.addTo(map);
}

function showError(message) {
  const box = L.DomUtil.create("div", "map-error", document.getElementById("map"));
  box.textContent = message;
}

fetch("/api/zones")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    const breaks = computeBreaks(data.features.map((f) => f.properties.trip_count));

    const layer = L.geoJSON(data, {
      style: (feature) => ({
        fillColor: colorFor(feature.properties.trip_count, breaks),
        fillOpacity: 0.7,
        color: "#555",
        weight: 1,
      }),
      onEachFeature: (feature, zoneLayer) => {
        const p = feature.properties;
        zoneLayer.bindTooltip(
          `<strong>${p.name}</strong><br>${p.borough}<br>${p.trip_count.toLocaleString()} pickups`,
          { sticky: true }
        );
        zoneLayer.on({
          mouseover: (e) => e.target.setStyle({ weight: 3, color: "#000" }).bringToFront(),
          mouseout: (e) => layer.resetStyle(e.target),
        });
      },
    }).addTo(map);

    map.fitBounds(layer.getBounds());
    addLegend(breaks, data.day, data.hour);
  })
  .catch(() => showError("Could not load taxi zones. Please refresh the page."));
