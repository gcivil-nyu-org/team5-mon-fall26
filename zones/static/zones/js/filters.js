// US4 #6 + US2 #4: time filters and two-zone selection (pickup + optional dropoff).
const dayFilter = document.getElementById("day-filter");
const hourFilter = document.getElementById("hour-filter");
const hourValue = document.getElementById("hour-value");
const filterStatus = document.getElementById("filter-status");
const pickupZoneEl = document.getElementById("pickup-zone");
const dropoffZoneEl = document.getElementById("dropoff-zone");
const clearPickupBtn = document.getElementById("clear-pickup");
const clearDropoffBtn = document.getElementById("clear-dropoff");
const clearSelectionBtn = document.getElementById("clear-selection");
const sameZoneBtn = document.getElementById("same-zone-trip");

let demandMap;
let zonesLayer;
let legendControl;
let displayedTime;
let pickupZoneId = null;
let dropoffZoneId = null;
let currentBreaks = [];
let requestSequence = 0;
let hourRequestTimer = null;
let sameZoneOutline = null;
const zoneLayers = new Map();

const PICKUP_COLOR = "#0057b8";
const DROPOFF_COLOR = "#00804a";

function updateHourLabel() {
  const hour = Number(hourFilter.value);
  hourValue.textContent = `${hour}:00–${hour}:59`;
}

// Select a pickup and dropoff together: a saved route (US13) or a cheaper
// nearby pickup (US19, via taxiscope:select-route).
function selectRoute(pickup, dropoff, unavailableMessage) {
  if (!zoneLayers.has(pickup) || !zoneLayers.has(dropoff)) {
    showError(unavailableMessage);
    return;
  }
  pickupZoneId = pickup;
  dropoffZoneId = dropoff;
  zonesLayer.setStyle(styleZone);
  zoneLayers.get(pickup)?.bringToFront();
  zoneLayers.get(dropoff)?.bringToFront();
  updateSameZoneOutline();
  updateSelectionPanel();
  document.dispatchEvent(
    new CustomEvent("taxiscope:zones-selected", {
      detail: { pickup: pickupZoneId, dropoff: dropoffZoneId },
    })
  );
}

// The fare line and the duration line are both written by fare.js from
// the same /api/routes response (US5 #7, US6 #8).
function updateSelectionPanel() {
  const pickupLayer = zoneLayers.get(pickupZoneId);
  const dropoffLayer = zoneLayers.get(dropoffZoneId);

  if (pickupLayer) {
    const p = pickupLayer.feature.properties;
    pickupZoneEl.textContent = `${p.name} (${p.borough})`;
    clearPickupBtn.hidden = false;
  } else {
    pickupZoneEl.textContent = "Click a zone";
    clearPickupBtn.hidden = true;
  }

  if (dropoffLayer && dropoffZoneId === pickupZoneId) {
    dropoffZoneEl.textContent = "same zone";
    clearDropoffBtn.hidden = false;
  } else if (dropoffLayer) {
    const p = dropoffLayer.feature.properties;
    dropoffZoneEl.textContent = `${p.name} (${p.borough})`;
    clearDropoffBtn.hidden = false;
  } else {
    dropoffZoneEl.textContent = pickupZoneId ? "Click another zone (optional)" : "—";
    clearDropoffBtn.hidden = true;
  }

  sameZoneBtn.hidden = !(pickupZoneId !== null && dropoffZoneId === null);
  clearSelectionBtn.hidden = pickupZoneId === null;
}

function styleZone(feature) {
  const zoneId = feature.properties.zone_id;
  const isPickup = zoneId === pickupZoneId;
  const isDropoff = zoneId === dropoffZoneId;

  // Trip within one zone: a thicker pickup border; the dashed dropoff
  // border is drawn on top by updateSameZoneOutline().
  if (isPickup && isDropoff) {
    return {
      fillColor: colorFor(feature.properties.trip_count, currentBreaks),
      fillOpacity: 0.9,
      color: PICKUP_COLOR,
      weight: 5,
    };
  }
  if (isPickup) {
    return {
      fillColor: colorFor(feature.properties.trip_count, currentBreaks),
      fillOpacity: 0.9,
      color: PICKUP_COLOR,
      weight: 3,
    };
  }
  if (isDropoff) {
    return {
      fillColor: colorFor(feature.properties.trip_count, currentBreaks),
      fillOpacity: 0.9,
      color: DROPOFF_COLOR,
      weight: 3,
    };
  }
  return {
    fillColor: colorFor(feature.properties.trip_count, currentBreaks),
    fillOpacity: 0.7,
    color: "#555",
    weight: 1,
  };
}

function selectZone(zoneId) {
  if (zoneId === pickupZoneId) {
    pickupZoneId = null;
    dropoffZoneId = null;
  } else if (zoneId === dropoffZoneId) {
    dropoffZoneId = null;
  } else if (pickupZoneId === null) {
    pickupZoneId = zoneId;
  } else {
    dropoffZoneId = zoneId;
  }

  zonesLayer.setStyle(styleZone);
  if (pickupZoneId) zoneLayers.get(pickupZoneId)?.bringToFront();
  if (dropoffZoneId) zoneLayers.get(dropoffZoneId)?.bringToFront();
  updateSameZoneOutline();
  updateSelectionPanel();
  document.dispatchEvent(
    new CustomEvent("taxiscope:zones-selected", {
      detail: { pickup: pickupZoneId, dropoff: dropoffZoneId },
    })
  );
}

function clearPickup() {
  pickupZoneId = null;
  dropoffZoneId = null;
  zonesLayer.setStyle(styleZone);
  updateSameZoneOutline();
  updateSelectionPanel();
  document.dispatchEvent(
    new CustomEvent("taxiscope:zones-selected", {
      detail: { pickup: null, dropoff: null },
    })
  );
}

function clearDropoff() {
  dropoffZoneId = null;
  zonesLayer.setStyle(styleZone);
  updateSameZoneOutline();
  updateSelectionPanel();
  document.dispatchEvent(
    new CustomEvent("taxiscope:zones-selected", {
      detail: { pickup: pickupZoneId, dropoff: null },
    })
  );
}

// US5 #7 follow-up: "Trip within this zone" sets the dropoff to the pickup.
function selectSameZone() {
  if (pickupZoneId === null) return;
  dropoffZoneId = pickupZoneId;
  zonesLayer.setStyle(styleZone);
  zoneLayers.get(pickupZoneId)?.bringToFront();
  updateSameZoneOutline();
  updateSelectionPanel();
  document.dispatchEvent(
    new CustomEvent("taxiscope:zones-selected", {
      detail: { pickup: pickupZoneId, dropoff: dropoffZoneId },
    })
  );
}

// A dashed dropoff border over the pickup border when both are the same
// zone. It sits in its own pane above the zones, so hovering a zone
// (which brings it to the front) never covers it.
function updateSameZoneOutline() {
  if (sameZoneOutline) {
    sameZoneOutline.remove();
    sameZoneOutline = null;
  }
  if (pickupZoneId === null || pickupZoneId !== dropoffZoneId) return;
  sameZoneOutline = L.geoJSON(zoneLayers.get(pickupZoneId).feature, {
    pane: "sameZonePane",
    interactive: false,
    style: { color: DROPOFF_COLOR, weight: 3, dashArray: "6 6", fill: false },
  }).addTo(demandMap);
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
    updateSelectionPanel();
    displayedTime = { day: data.day, hour: data.hour };
    document.dispatchEvent(new CustomEvent("taxiscope:time-changed", { detail: { ...displayedTime } }));
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
    zoneLayer.on("click", () => selectZone(zoneId));
  });
  zonesLayer.options.style = styleZone;
  zonesLayer.setStyle(styleZone);

  // Above the zones (overlayPane, 400), below tooltips; clicks pass through.
  const sameZonePane = demandMap.createPane("sameZonePane");
  sameZonePane.style.zIndex = 450;
  sameZonePane.style.pointerEvents = "none";

  clearPickupBtn.addEventListener("click", clearPickup);
  clearDropoffBtn.addEventListener("click", clearDropoff);
  clearSelectionBtn.addEventListener("click", clearPickup);
  sameZoneBtn.addEventListener("click", selectSameZone);

  if (document.body.dataset.savedPickup && document.body.dataset.savedDropoff) {
    selectRoute(
      Number(document.body.dataset.savedPickup),
      Number(document.body.dataset.savedDropoff),
      "This saved route's zones are unavailable."
    );
  }

  document.addEventListener("taxiscope:select-route", (event) => {
    selectRoute(event.detail.pickup, event.detail.dropoff, "This zone is unavailable.");
  });

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
