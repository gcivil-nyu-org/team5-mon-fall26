// US4 #6: extend the demand map with time filters and selected-zone statistics.
const dayFilter = document.getElementById("day-filter");
const hourFilter = document.getElementById("hour-filter");
const hourValue = document.getElementById("hour-value");
const filterStatus = document.getElementById("filter-status");
const selectedZone = document.getElementById("selected-zone");
const fareRange = document.getElementById("fare-range");
const tripDuration = document.getElementById("trip-duration");

let demandMap;
let zonesLayer;
let legendControl;
let displayedTime;
let selectedZoneId = null;
let currentBreaks = [];
let requestSequence = 0;
let hourRequestTimer = null;
const zoneLayers = new Map();

function updateHourLabel() {
  const hour = Number(hourFilter.value);
  hourValue.textContent = `${hour}:00–${hour}:59`;
}

function updateSelectedZone(feature) {
  if (!feature) {
    selectedZone.textContent = "Select a zone";
    fareRange.textContent = "—";
    tripDuration.textContent = "—";
    return;
  }

  const props = feature.properties;
  selectedZone.textContent = `${props.name} (${props.borough})`;
  if (props.trip_count === 0 || props.fare_min === null) {
    fareRange.textContent = "Not enough data";
    tripDuration.textContent = "Not enough data";
    return;
  }

  fareRange.textContent = `$${Number(props.fare_min).toFixed(2)}–$${Number(props.fare_max).toFixed(2)}`;
  tripDuration.textContent = `${Number(props.avg_duration_min).toFixed(1)} min`;
}

function styleZone(feature) {
  const selected = feature.properties.zone_id === selectedZoneId;
  return {
    fillColor: colorFor(feature.properties.trip_count, currentBreaks),
    fillOpacity: selected ? 0.9 : 0.7,
    color: selected ? "#000" : "#555",
    weight: selected ? 3 : 1,
  };
}

async function reloadZones() {
  const sequence = ++requestSequence;
  const day = Number(dayFilter.value);
  const hour = Number(hourFilter.value);
  filterStatus.textContent = "Updating…";
  document.body.classList.add("is-loading");

  try {
    const response = await fetch(`/api/zones?day=${day}&hour=${hour}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (sequence !== requestSequence) return;

    const featuresById = new Map(data.features.map((feature) => [feature.properties.zone_id, feature]));
    currentBreaks = computeBreaks(data.features.map((feature) => feature.properties.trip_count));
    zoneLayers.forEach((zoneLayer, zoneId) => {
      const feature = featuresById.get(zoneId);
      if (!feature) return;
      zoneLayer.feature.properties = feature.properties;
      const props = feature.properties;
      zoneLayer.setTooltipContent(
        `<strong>${props.name}</strong><br>${props.borough}<br>${props.trip_count.toLocaleString()} pickups`
      );
    });
    zonesLayer.setStyle(styleZone);

    demandMap.removeControl(legendControl);
    legendControl = addLegend(currentBreaks, data.day, data.hour);
    updateSelectedZone(zoneLayers.get(selectedZoneId)?.feature);
    displayedTime = { day: data.day, hour: data.hour };
    filterStatus.textContent = `Showing ${DAYS[data.day]} ${data.hour}:00–${data.hour}:59`;
    document.querySelector(".map-error")?.remove();
  } catch {
    if (sequence !== requestSequence) return;
    dayFilter.value = displayedTime.day;
    hourFilter.value = displayedTime.hour;
    updateHourLabel();
    filterStatus.textContent = `Update failed; showing ${DAYS[displayedTime.day]} ${displayedTime.hour}:00–${displayedTime.hour}:59`;
    document.querySelector(".map-error")?.remove();
    showError("Could not load taxi data for this time. Please try again.");
  } finally {
    if (sequence === requestSequence) document.body.classList.remove("is-loading");
  }
}

document.addEventListener("taxiscope:map-ready", (event) => {
  ({ map: demandMap, layer: zonesLayer, legend: legendControl } = event.detail);
  displayedTime = { day: event.detail.data.day, hour: event.detail.data.hour };
  currentBreaks = computeBreaks(event.detail.data.features.map((feature) => feature.properties.trip_count));
  dayFilter.value = displayedTime.day;
  hourFilter.value = displayedTime.hour;
  updateHourLabel();
  filterStatus.textContent = `Showing ${DAYS[displayedTime.day]} ${displayedTime.hour}:00–${displayedTime.hour}:59`;

  zonesLayer.eachLayer((zoneLayer) => {
    const zoneId = zoneLayer.feature.properties.zone_id;
    zoneLayers.set(zoneId, zoneLayer);
    zoneLayer.on("click", () => {
      selectedZoneId = zoneId;
      zonesLayer.setStyle(styleZone);
      updateSelectedZone(zoneLayer.feature);
    });
  });
  zonesLayer.options.style = styleZone;
  zonesLayer.setStyle(styleZone);

  dayFilter.addEventListener("change", () => {
    window.clearTimeout(hourRequestTimer);
    reloadZones();
  });
  hourFilter.addEventListener("input", () => {
    updateHourLabel();
    ++requestSequence;
    window.clearTimeout(hourRequestTimer);
    hourRequestTimer = window.setTimeout(reloadZones, 180);
  });
});
