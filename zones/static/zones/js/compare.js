// US22 #69: compare two zones side by side. Uses map.js (the demand map)
// and heatmap.js (TaxiScopeHeatmap) unchanged; filters.js is not loaded.
(function () {
  "use strict";

  const A_COLOR = "#0057b8"; // the map's pickup blue
  const B_COLOR = "#00804a"; // the map's dropoff green
  const SIDES = ["a", "b"];
  const LABEL = { a: "A", b: "B" };
  const minTrips = Number(document.body.dataset.minTripCount);

  const dayFilter = document.getElementById("day-filter");
  const hourFilter = document.getElementById("hour-filter");
  const hourValue = document.getElementById("hour-value");
  const filterStatus = document.getElementById("filter-status");
  const message = document.getElementById("compare-message");
  const table = document.getElementById("compare-table");
  const when = document.getElementById("compare-when");
  const marks = document.getElementById("compare-marks");
  const weeklyToggle = document.getElementById("weekly-toggle");
  const weeklyStrip = document.getElementById("weekly-strip");
  const weeklyClose = document.getElementById("weekly-close");
  const metricRadios = document.querySelectorAll('input[name="compare-metric"]');
  const swapButton = document.getElementById("swap-zones");
  const keyLow = document.getElementById("weekly-key-low");
  const keyHigh = document.getElementById("weekly-key-high");
  // The day and hour the page was opened with (the address, or now).
  const requestedTime = { day: Number(dayFilter.value), hour: Number(hourFilter.value) };

  const ui = {};
  for (const side of SIDES) {
    const get = (suffix) => document.getElementById(`${side}-${suffix}`);
    ui[side] = {
      zone: document.getElementById(`compare-${side}-zone`),
      clear: document.getElementById(`clear-${side}`),
      fare: get("fare"),
      fareAvg: get("fare-avg"),
      fareRange: get("fare-range"),
      time: get("time"),
      trips: get("trips"),
      busiest: get("busiest"),
      choose: get("choose"),
      weekly: document.getElementById(`weekly-${side}`),
      weeklyTitle: document.getElementById(`weekly-${side}-title`),
    };
  }

  // One entry per side. The sequence numbers live outside it, so a response
  // for a zone that has since been replaced is still recognised as stale.
  const state = { a: emptySide(null), b: emptySide(null) };
  const sequence = { a: { stats: 0, heatmap: 0 }, b: { stats: 0, heatmap: 0 } };

  let demandMap;
  let zonesLayer;
  let legendControl;
  let displayedTime;
  let currentBreaks = [];
  let requestSequence = 0;
  let hourRequestTimer = null;
  let weeklyOpen = false;
  // True while the first reload to the address's day and hour is running.
  let waitingForStart = false;
  const zoneLayers = new Map();
  const labels = { a: null, b: null };

  function emptySide(zone) {
    return { zone, stats: null, statsError: false, heatmap: null, heatmapError: false };
  }

  function other(side) {
    return side === "a" ? "b" : "a";
  }

  function dollars(value) {
    return `$${Number(value).toFixed(2)}`;
  }

  function tripsLabel(count) {
    return `${count.toLocaleString()} ${count === 1 ? "trip" : "trips"}`;
  }

  function zoneName(zoneId) {
    const p = zoneLayers.get(zoneId).feature.properties;
    return `${p.name} (${p.borough})`;
  }

  function timeLabel(time) {
    return `${DAYS[time.day]} ${time.hour}:00–${time.hour}:59`;
  }

  function showMessage(text) {
    message.textContent = text;
  }

  // The address keeps the comparison, so Refresh and Back show it again.
  function updateAddress() {
    if (!displayedTime || waitingForStart) return;
    const params = new URLSearchParams();
    for (const side of SIDES) {
      if (state[side].zone !== null) params.set(side, state[side].zone);
    }
    params.set("day", displayedTime.day);
    params.set("hour", displayedTime.hour);
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }

  // ---- Picking ----

  // A map click: clicking A or B again unselects it; otherwise the click
  // fills the first empty side, or replaces B when both are set.
  function clickZone(zoneId) {
    if (zoneId === state.a.zone) return setZone("a", null);
    if (zoneId === state.b.zone) return setZone("b", null);
    setZone(state.a.zone === null ? "a" : "b", zoneId);
  }

  function setZone(side, zoneId) {
    if (zoneId !== null && zoneId === state[other(side)].zone) {
      showMessage(`That zone is already ${LABEL[other(side)]}. Pick a different zone for ${LABEL[side]}.`);
      return;
    }
    if (zoneId !== null && !zoneLayers.has(zoneId)) {
      showMessage("This zone is unavailable.");
      return;
    }
    showMessage("");
    sequence[side].stats += 1;
    sequence[side].heatmap += 1;
    state[side] = emptySide(zoneId);
    restyle();
    updateLabels();
    renderCard();
    renderWeekly();
    if (zoneId !== null) {
      loadStats(side);
      loadHeatmap(side);
    }
    updateAddress();
  }

  function swapZones() {
    if (state.a.zone === null || state.b.zone === null) return;
    [state.a, state.b] = [state.b, state.a];
    // Responses still on their way belong to the old sides: drop them and
    // ask again for whatever had not arrived yet.
    for (const side of SIDES) {
      sequence[side].stats += 1;
      sequence[side].heatmap += 1;
      const column = state[side];
      if (column.stats === null && !column.statsError) loadStats(side);
      if (column.heatmap === null && !column.heatmapError) loadHeatmap(side);
    }
    showMessage("");
    restyle();
    updateLabels();
    renderCard();
    renderWeekly();
    updateAddress();
  }

  function styleZone(feature) {
    const zoneId = feature.properties.zone_id;
    const fillColor = colorFor(feature.properties.trip_count, currentBreaks);
    if (zoneId === state.a.zone) return { fillColor, fillOpacity: 0.9, color: A_COLOR, weight: 3 };
    if (zoneId === state.b.zone) return { fillColor, fillOpacity: 0.9, color: B_COLOR, weight: 3 };
    return { fillColor, fillOpacity: 0.7, color: "#555", weight: 1 };
  }

  function restyle() {
    zonesLayer.setStyle(styleZone);
    for (const side of SIDES) zoneLayers.get(state[side].zone)?.bringToFront();
  }

  // An "A" or "B" badge in the middle of each picked zone.
  function updateLabels() {
    for (const side of SIDES) {
      labels[side]?.remove();
      labels[side] = null;
      const zoneLayer = zoneLayers.get(state[side].zone);
      if (!zoneLayer) continue;
      labels[side] = L.marker(zoneLayer.getBounds().getCenter(), {
        pane: "compareLabelPane",
        interactive: false,
        keyboard: false,
        icon: L.divIcon({
          className: `compare-zone-label compare-zone-label-${side}`,
          html: LABEL[side],
          iconSize: [22, 22],
        }),
      }).addTo(demandMap);
    }
  }

  // ---- The card ----

  function renderCard() {
    const a = state.a.zone;
    const b = state.b.zone;
    ui.a.zone.textContent = a === null ? "Click a zone on the map to set A" : zoneName(a);
    if (b !== null) ui.b.zone.textContent = zoneName(b);
    else ui.b.zone.textContent = a === null ? "—" : "Click a second zone";
    for (const side of SIDES) {
      ui[side].clear.hidden = state[side].zone === null;
      renderColumn(side);
    }
    swapButton.hidden = a === null || b === null;
    table.hidden = a === null && b === null;
    if (displayedTime) when.textContent = timeLabel(displayedTime);
    renderMarks();
  }

  function renderColumn(side) {
    const column = state[side];
    const cells = ui[side];
    const stats = column.stats;
    cells.fareRange.textContent = "";
    if (column.zone === null) {
      cells.fareAvg.textContent = "—";
      cells.time.textContent = "—";
      cells.trips.textContent = "—";
    } else if (column.statsError) {
      cells.fareAvg.textContent = "Could not load";
      cells.time.textContent = "Could not load";
      cells.trips.textContent = "Could not load";
    } else if (stats === null) {
      cells.fareAvg.textContent = "Loading…";
      cells.time.textContent = "Loading…";
      cells.trips.textContent = "Loading…";
    } else if (!stats.enough_data) {
      // The real count stays, so the rider sees why (US5).
      cells.fareAvg.textContent = "Not enough data";
      cells.time.textContent = "Not enough data";
      cells.trips.textContent = tripsLabel(stats.trip_count);
    } else {
      cells.fareAvg.textContent = dollars(stats.fare_avg);
      cells.fareRange.textContent = `${dollars(stats.fare_min)}–${dollars(stats.fare_max)}`;
      cells.time.textContent = `${Number(stats.avg_duration_min).toFixed(1)} min`;
      cells.trips.textContent = tripsLabel(stats.trip_count);
    }
    cells.busiest.textContent = busiestText(column);
  }

  // The hour of the shown day with the most trips, from the heatmap already
  // loaded; the earlier hour wins a tie. Null when even that hour has fewer
  // than MIN_TRIP_COUNT trips. (Not the cheapest or fastest hour: US7 keeps
  // best and worst times to a trip.)
  function busiestHour(heatmap, day) {
    const hours = heatmap.heatmap[day];
    let best = null;
    hours.forEach((cell, hour) => {
      if (cell.trip_count !== null && (best === null || cell.trip_count > hours[best].trip_count)) best = hour;
    });
    return best !== null && hours[best].trip_count >= minTrips ? best : null;
  }

  function busiestText(column) {
    if (column.zone === null) return "—";
    if (column.heatmapError) return "Could not load";
    if (column.heatmap === null || !displayedTime) return "Loading…";
    const hour = busiestHour(column.heatmap, displayedTime.day);
    return hour === null ? "Not enough data" : `${hour}:00–${hour}:59`;
  }

  // Cheaper and faster, compared at the precision shown in the table
  // (cents, tenths of a minute). Only when both columns have enough data.
  function compareMarks(a, b) {
    const short = SIDES.filter((side) => !(side === "a" ? a : b).enough_data);
    if (short.length === 2) {
      return { text: `Can't compare: A and B have fewer than ${minTrips} trips at this hour.` };
    }
    if (short.length === 1) {
      return { text: `Can't compare: ${LABEL[short[0]]} has fewer than ${minTrips} trips at this hour.` };
    }
    const cents = (value) => Math.round(Number(Number(value).toFixed(2)) * 100);
    const tenths = (value) => Math.round(Number(Number(value).toFixed(1)) * 10);
    const fareDiff = cents(a.fare_avg) - cents(b.fare_avg);
    const timeDiff = tenths(a.avg_duration_min) - tenths(b.avg_duration_min);
    const winner = (diff) => (diff < 0 ? "a" : diff > 0 ? "b" : null);
    const fare = winner(fareDiff);
    const time = winner(timeDiff);
    const fareBy = `$${(Math.abs(fareDiff) / 100).toFixed(2)}`;
    const timeBy = `${(Math.abs(timeDiff) / 10).toFixed(1)} min`;
    if (fare && fare === time) {
      return { fare, time, text: `${LABEL[fare]} is cheaper by ${fareBy} and faster by ${timeBy}.` };
    }
    const fareText = fare ? `${LABEL[fare]} is cheaper by ${fareBy}` : "Same typical fare";
    const timeText = time ? `${LABEL[time]} is faster by ${timeBy}` : "Same typical time";
    return { fare, time, text: `${fareText}. ${timeText}.` };
  }

  function renderMarks() {
    const a = state.a.stats;
    const b = state.b.stats;
    const result = a && b ? compareMarks(a, b) : { text: "" };
    marks.textContent = result.text;
    for (const side of SIDES) {
      ui[side].fare.classList.toggle("is-better", result.fare === side);
      ui[side].time.classList.toggle("is-better", result.time === side);
    }
  }

  // ---- Data, one column at a time; only the newest response is used ----

  function loadStats(side) {
    const zone = state[side].zone;
    if (zone === null || !displayedTime || waitingForStart) return;
    const current = ++sequence[side].stats;
    state[side].stats = null;
    state[side].statsError = false;
    renderColumn(side);
    renderMarks();
    const params = new URLSearchParams({ from: zone, day: displayedTime.day, hour: displayedTime.hour });
    fetch(`/api/routes?${params}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (current !== sequence[side].stats) return;
        state[side].stats = data;
        renderColumn(side);
        renderMarks();
      })
      .catch((error) => {
        if (current !== sequence[side].stats) return;
        console.error("Compare error:", error);
        state[side].statsError = true;
        renderColumn(side);
        renderMarks();
      });
  }

  function loadHeatmap(side) {
    const zone = state[side].zone;
    const current = ++sequence[side].heatmap;
    fetch(`/api/zones/${zone}/heatmap`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (current !== sequence[side].heatmap) return;
        state[side].heatmap = data;
        renderColumn(side);
        renderWeekly();
      })
      .catch((error) => {
        if (current !== sequence[side].heatmap) return;
        console.error("Compare heatmap error:", error);
        state[side].heatmapError = true;
        renderColumn(side);
        renderWeekly();
      });
  }

  // ---- Weekly pattern strip ----

  function setWeeklyOpen(open) {
    weeklyOpen = open;
    weeklyStrip.hidden = !open;
    weeklyToggle.textContent = open ? "Hide weekly pattern" : "Show weekly pattern";
    weeklyToggle.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("weekly-open", open);
    renderWeekly();
  }

  // The legend (bottom right of the map) moves up above the open strip.
  function updateStripSpace() {
    const height = weeklyOpen ? `${weeklyStrip.offsetHeight}px` : "0px";
    document.body.style.setProperty("--weekly-height", height);
  }

  function note(container, text) {
    container.innerHTML = "";
    const p = document.createElement("p");
    p.className = "weekly-note";
    p.textContent = text;
    container.appendChild(p);
  }

  function renderWeekly() {
    if (!weeklyOpen) {
      updateStripSpace();
      return;
    }
    const metric = document.querySelector('input[name="compare-metric"]:checked').value;
    const { renderGrid, valueRange } = window.TaxiScopeHeatmap;
    keyLow.textContent = metric === "trip_count" ? "Fewer" : "Shorter";
    keyHigh.textContent = metric === "trip_count" ? "more trips" : "longer avg time";
    // One colour scale for both grids, so the same colour means the same value.
    const ranges = SIDES.map((side) => state[side].heatmap && valueRange(state[side].heatmap, metric))
      .filter(Boolean);
    const range = ranges.length
      ? { min: Math.min(...ranges.map((r) => r.min)), max: Math.max(...ranges.map((r) => r.max)) }
      : null;

    for (const side of SIDES) {
      const column = state[side];
      const cells = ui[side];
      cells.weeklyTitle.textContent = column.zone === null
        ? LABEL[side]
        : `${LABEL[side]}: ${zoneName(column.zone)}`;
      if (column.zone === null) {
        note(cells.weekly, `Pick zone ${LABEL[side]} on the map`);
      } else if (column.heatmapError) {
        note(cells.weekly, "Could not load the weekly pattern.");
      } else if (column.heatmap === null) {
        note(cells.weekly, "Loading…");
      } else if (valueRange(column.heatmap, "trip_count") === null) {
        note(cells.weekly, "No trips recorded");
      } else {
        renderGrid(cells.weekly, column.heatmap, metric, { highlight: displayedTime, range });
      }
    }
    updateStripSpace();
  }

  // ---- Day and hour filters ----

  function updateHourLabel() {
    const hour = Number(hourFilter.value);
    hourValue.textContent = `${hour}:00–${hour}:59`;
  }

  // Copied from reloadZones() in filters.js (US4 #6), so the map page's
  // script stays untouched (US22 decision). Differences: it restyles with
  // this page's A/B outlines and then reloads both columns and the strip.
  async function reloadZones() {
    const current = ++requestSequence;
    const day = Number(dayFilter.value);
    const hour = Number(hourFilter.value);
    filterStatus.textContent = "Updating…";
    document.body.classList.add("is-loading");

    try {
      const response = await fetch(`/api/zones?day=${day}&hour=${hour}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (current !== requestSequence) return;

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
      restyle();

      demandMap.removeControl(legendControl);
      legendControl = addLegend(currentBreaks, data.day, data.hour);
      displayedTime = { day: data.day, hour: data.hour };
      filterStatus.textContent = `Showing ${timeLabel(displayedTime)}`;
      document.querySelector(".map-error")?.remove();
      // Both columns follow the new day and hour together.
      waitingForStart = false;
      SIDES.forEach(loadStats);
      renderCard();
      renderWeekly();
      updateAddress();
    } catch {
      if (current !== requestSequence) return;
      dayFilter.value = displayedTime.day;
      hourFilter.value = displayedTime.hour;
      updateHourLabel();
      filterStatus.textContent = `Update failed; showing ${timeLabel(displayedTime)}`;
      document.querySelector(".map-error")?.remove();
      showError("Could not load taxi data for this time. Please try again.");
      if (waitingForStart) {
        // The address's time could not be loaded: stay on the map's time.
        waitingForStart = false;
        SIDES.forEach(loadStats);
        renderCard();
        updateAddress();
      }
    } finally {
      if (current === requestSequence) document.body.classList.remove("is-loading");
    }
  }

  document.addEventListener("taxiscope:map-ready", (event) => {
    ({ map: demandMap, layer: zonesLayer, legend: legendControl } = event.detail);
    displayedTime = { day: event.detail.data.day, hour: event.detail.data.hour };
    currentBreaks = computeBreaks(event.detail.data.features.map((feature) => feature.properties.trip_count));
    // map.js always loads the current time; the address may ask for another.
    waitingForStart = requestedTime.day !== displayedTime.day || requestedTime.hour !== displayedTime.hour;
    if (!waitingForStart) {
      dayFilter.value = displayedTime.day;
      hourFilter.value = displayedTime.hour;
      updateHourLabel();
      filterStatus.textContent = `Showing ${timeLabel(displayedTime)}`;
    }

    zonesLayer.eachLayer((zoneLayer) => {
      const zoneId = zoneLayer.feature.properties.zone_id;
      zoneLayers.set(zoneId, zoneLayer);
      zoneLayer.on("click", () => clickZone(zoneId));
    });
    zonesLayer.options.style = styleZone;
    zonesLayer.setStyle(styleZone);

    // Above the zones (overlayPane, 400), below tooltips; clicks pass through.
    const labelPane = demandMap.createPane("compareLabelPane");
    labelPane.style.zIndex = 450;
    labelPane.style.pointerEvents = "none";

    for (const side of SIDES) {
      ui[side].clear.addEventListener("click", () => setZone(side, null));
      // "or choose from list": the list picks a zone, then resets.
      ui[side].choose.addEventListener("change", () => {
        const value = ui[side].choose.value;
        ui[side].choose.value = "";
        if (value !== "") setZone(side, Number(value));
      });
    }
    swapButton.addEventListener("click", swapZones);

    // Zones from the address; the server's note about the link stays.
    const linkMessage = message.textContent;
    const startA = Number(document.body.dataset.startA) || null;
    const startB = Number(document.body.dataset.startB) || null;
    if (startA !== null) setZone("a", startA);
    if (startB !== null) setZone("b", startB);
    showMessage(linkMessage);
    renderCard();
    if (waitingForStart) reloadZones();

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

  weeklyToggle.addEventListener("click", () => setWeeklyOpen(!weeklyOpen));
  weeklyClose.addEventListener("click", () => setWeeklyOpen(false));
  metricRadios.forEach((radio) => radio.addEventListener("change", renderWeekly));
  window.addEventListener("resize", updateStripSpace);
})();
