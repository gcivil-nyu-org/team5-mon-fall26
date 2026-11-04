// US22 #69: compare two zones side by side (the compare page's card and strip).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const jsRoot = path.join(__dirname, "../static/zones/js");
const sources = ["heatmap.js", "compare.js"].map(name =>
  fs.readFileSync(path.join(jsRoot, name), "utf8")
);
const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
};

function fakeElement(tag = "div") {
  const element = {
    tagName: tag, className: "", title: "", textContent: "", hidden: false, value: "",
    style: {}, children: [], listeners: {}, attributes: {}, offsetHeight: 240,
    classList: {
      add(name) { if (!element.classList.contains(name)) element.className = `${element.className} ${name}`.trim(); },
      remove(name) { element.className = element.className.split(" ").filter(c => c && c !== name).join(" "); },
      toggle(name, on) { on ? element.classList.add(name) : element.classList.remove(name); },
      contains(name) { return element.className.split(" ").includes(name); },
    },
    appendChild(child) { element.children.push(child); return child; },
    addEventListener(name, fn) { element.listeners[name] = fn; },
    setAttribute(name, value) { element.attributes[name] = value; },
  };
  Object.defineProperty(element, "innerHTML", {
    get() { return element._html ?? ""; },
    set(value) { element._html = value; element.children = []; },
  });
  return element;
}

const ZONES = {
  1: { name: "Astoria", borough: "Queens" },
  2: { name: "Midtown Center", borough: "Manhattan" },
  3: { name: "Harlem", borough: "Manhattan" },
};

function emptyHeatmap() {
  return Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => ({ trip_count: null, avg_duration_min: null }))
  );
}

function heatmapWith(cells) {
  const heatmap = emptyHeatmap();
  for (const [key, value] of Object.entries(cells)) {
    const [day, hour] = key.split(",").map(Number);
    heatmap[day][hour] = value;
  }
  return { heatmap };
}

const enough = (fare_avg, avg_duration_min, extra = {}) => ({
  enough_data: true, trip_count: 40, fare_min: "5.00", fare_avg, fare_max: "90.00",
  avg_duration_min, ...extra,
});
const tooFew = trip_count => ({
  enough_data: false, trip_count, fare_min: null, fare_avg: null, fare_max: null,
  avg_duration_min: null,
});

function setup({ stats = {}, heatmaps = {}, start = {}, zonesFail = false } = {}) {
  const elements = {};
  const listeners = {};
  const requests = [];
  const held = [];
  const markers = [];
  const errors = [];
  const addresses = [];
  const ids = [
    "day-filter", "hour-filter", "hour-value", "filter-status", "compare-message",
    "compare-a-zone", "compare-b-zone", "clear-a", "clear-b", "compare-table",
    "compare-when", "compare-marks", "weekly-toggle", "weekly-strip", "weekly-close",
    "weekly-a", "weekly-b", "weekly-a-title", "weekly-b-title",
    "swap-zones", "a-choose", "b-choose", "weekly-key-low", "weekly-key-high",
  ];
  for (const side of ["a", "b"]) {
    for (const cell of ["fare", "fare-avg", "fare-range", "time", "trips", "busiest"]) ids.push(`${side}-${cell}`);
  }
  for (const id of ids) elements[id] = fakeElement();
  elements["compare-table"].hidden = true;
  elements["weekly-strip"].hidden = true;
  elements["clear-a"].hidden = true;
  elements["clear-b"].hidden = true;
  elements["swap-zones"].hidden = true;
  elements["day-filter"].value = String(start.day ?? 1);
  elements["hour-filter"].value = String(start.hour ?? 17);
  elements["compare-message"].textContent = start.message ?? "";
  elements["weekly-key-low"].textContent = "Fewer";
  elements["weekly-key-high"].textContent = "more trips";
  const metric = { value: "trip_count", listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; } };
  const radios = [metric];

  const body = fakeElement("body");
  body.dataset = { minTripCount: "5", startA: String(start.a ?? ""), startB: String(start.b ?? "") };
  body.style.setProperty = (name, value) => { body.style[name] = value; };

  const document = {
    body,
    getElementById(id) { return elements[id] ?? null; },
    createElement: fakeElement,
    querySelector(selector) {
      if (selector.includes("compare-metric")) return metric;
      return null;
    },
    querySelectorAll(selector) { return selector.includes("compare-metric") ? radios : []; },
    addEventListener(name, fn) { (listeners[name] ??= []).push(fn); },
    dispatchEvent(event) { for (const fn of listeners[event.type] ?? []) fn(event); },
  };

  const zoneLayers = {};
  const styles = {};
  for (const [id, props] of Object.entries(ZONES)) {
    zoneLayers[id] = {
      feature: { properties: { zone_id: Number(id), trip_count: 10, ...props } },
      handlers: {},
      on(name, fn) { this.handlers[name] = fn; },
      bringToFront() {},
      getBounds() { return { getCenter() { return [40.7, -74]; } }; },
      setTooltipContent(html) { this.tooltip = html; },
    };
  }
  const layer = {
    options: {},
    eachLayer(fn) { Object.values(zoneLayers).forEach(fn); },
    setStyle(fn) {
      for (const [id, zoneLayer] of Object.entries(zoneLayers)) styles[id] = fn(zoneLayer.feature);
    },
  };
  const panes = {};
  const map = {
    createPane(name) { panes[name] = { style: {} }; return panes[name]; },
    removeControl() {},
  };

  function respond(data, ok = true) {
    return Promise.resolve({ ok, status: ok ? 200 : 500, json: async () => data });
  }
  const context = {
    console: { error() {} },
    document,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    URLSearchParams,
    DAYS: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    computeBreaks() { return []; },
    colorFor() { return "#fff"; },
    addLegend(breaks, day, hour) { return { day, hour }; },
    showError(message) { errors.push(message); },
    L: {
      marker(latlng, options) {
        const marker = {
          latlng, options, removed: false,
          addTo() { markers.push(marker); return marker; },
          remove() { marker.removed = true; },
        };
        return marker;
      },
      divIcon(options) { return options; },
    },
    setTimeout, clearTimeout,
    location: { pathname: "/compare/" },
    history: { replaceState(state, title, url) { addresses.push(url); } },
    addEventListener() {},
    fetch(url) {
      requests.push(url);
      const [route, query] = url.split("?");
      const params = new URLSearchParams(query);
      if (route === "/api/zones") {
        if (zonesFail) return respond({}, false);
        const features = Object.values(zoneLayers).map(z => ({ properties: { ...z.feature.properties } }));
        return respond({ day: Number(params.get("day")), hour: Number(params.get("hour")), features });
      }
      if (route === "/api/routes") {
        const from = params.get("from");
        const answer = stats[from];
        const data = typeof answer === "function" ? answer(Number(params.get("day")), Number(params.get("hour"))) : answer;
        if (data === "error") return respond({}, false);
        if (data === "hold") return new Promise(resolve => held.push({ from, params, resolve }));
        return respond(data);
      }
      const match = route.match(/^\/api\/zones\/(\d+)\/heatmap$/);
      if (match) return respond(heatmaps[match[1]] ?? heatmapWith({}));
      throw new Error(`unexpected ${url}`);
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const source of sources) vm.runInContext(source, context);

  const ui = {
    elements, requests, held, markers, styles, panes, errors, metric, body, addresses,
    text(id) { return elements[id].textContent; },
    async ready(day = 1, hour = 17) {
      document.dispatchEvent({
        type: "taxiscope:map-ready",
        detail: { map, layer, legend: {}, data: { day, hour, features: [] } },
      });
      await settle();
    },
    async click(zoneId) {
      zoneLayers[zoneId].handlers.click();
      await settle();
    },
    async changeDay(day) {
      elements["day-filter"].value = String(day);
      elements["day-filter"].listeners.change();
      await settle();
    },
    async choose(side, zoneId) {
      elements[`${side}-choose`].value = String(zoneId);
      elements[`${side}-choose`].listeners.change();
      await settle();
    },
    async press(id) {
      elements[id].listeners.click();
      await settle();
    },
    liveMarkers() { return markers.filter(m => !m.removed).map(m => m.options.icon.html); },
    routeRequests() { return requests.filter(url => url.startsWith("/api/routes?")); },
    grid(side) { return elements[`weekly-${side}`].children[0]; },
    cell(side, day, hour) { return ui.grid(side).children[day + 1].children[hour + 1]; },
  };
  return ui;
}

test("guiding text: nothing picked, then A picked", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10) } });
  await ui.ready();
  assert.equal(ui.text("compare-a-zone"), "Click a zone on the map to set A");
  assert.equal(ui.text("compare-b-zone"), "—");
  assert.equal(ui.elements["compare-table"].hidden, true);

  await ui.click(1);
  assert.equal(ui.text("compare-a-zone"), "Astoria (Queens)");
  assert.equal(ui.text("compare-b-zone"), "Click a second zone");
  assert.equal(ui.elements["compare-table"].hidden, false);
  assert.equal(ui.text("a-fare-avg"), "$12.30");
  assert.equal(ui.text("a-fare-range"), "$5.00–$90.00");
  assert.equal(ui.text("a-time"), "10.0 min");
  assert.equal(ui.text("a-trips"), "40 trips");
  assert.equal(ui.text("b-fare-avg"), "—");
  assert.equal(ui.text("compare-when"), "Tuesday 17:00–17:59");
  assert.equal(ui.text("compare-marks"), "");
});

test("pick two zones: first click A, next B, outlined blue and green with labels", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);

  assert.equal(ui.text("compare-b-zone"), "Midtown Center (Manhattan)");
  assert.equal(ui.styles[1].color, "#0057b8");
  assert.equal(ui.styles[1].weight, 3);
  assert.equal(ui.styles[2].color, "#00804a");
  assert.equal(ui.styles[2].weight, 3);
  assert.equal(ui.styles[3].color, "#555");
  assert.deepEqual(ui.liveMarkers().sort(), ["A", "B"]);
  assert.equal(ui.elements["clear-a"].hidden, false);
  assert.equal(ui.elements["clear-b"].hidden, false);
  // Labels sit in their own pane that lets clicks through to the zones.
  assert.equal(ui.panes.compareLabelPane.style.pointerEvents, "none");
});

test("clicking A or B again unselects it; a click fills the first empty side", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8), 3: enough("30.00", 20) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);

  await ui.click(1);
  assert.equal(ui.text("compare-a-zone"), "Click a zone on the map to set A");
  assert.equal(ui.text("compare-b-zone"), "Midtown Center (Manhattan)");
  assert.equal(ui.text("a-fare-avg"), "—");
  assert.deepEqual(ui.liveMarkers(), ["B"]);
  assert.equal(ui.styles[1].color, "#555");

  await ui.click(3);
  assert.equal(ui.text("compare-a-zone"), "Harlem (Manhattan)");
  assert.equal(ui.text("compare-b-zone"), "Midtown Center (Manhattan)");

  await ui.click(2);
  assert.equal(ui.text("compare-b-zone"), "Click a second zone");
  await ui.click(1);
  assert.equal(ui.text("compare-b-zone"), "Astoria (Queens)");
});

test("the × buttons clear their side", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  await ui.press("clear-b");
  assert.equal(ui.text("compare-b-zone"), "Click a second zone");
  assert.equal(ui.elements["clear-b"].hidden, true);
  await ui.press("clear-a");
  assert.equal(ui.text("compare-a-zone"), "Click a zone on the map to set A");
  assert.equal(ui.text("compare-b-zone"), "—");
  assert.equal(ui.elements["compare-table"].hidden, true);
  assert.deepEqual(ui.liveMarkers(), []);
});

test("each column reads /api/routes without `to`, and the zone's heatmap", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.deepEqual(ui.routeRequests(), [
    "/api/routes?from=1&day=1&hour=17",
    "/api/routes?from=2&day=1&hour=17",
  ]);
  assert.ok(ui.requests.includes("/api/zones/1/heatmap"));
  assert.ok(ui.requests.includes("/api/zones/2/heatmap"));
});

test("the cheaper and faster zone is marked, with one sentence", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("compare-marks"), "A is cheaper by $48.20 and faster by 22.8 min.");
  assert.equal(ui.elements["a-fare"].classList.contains("is-better"), true);
  assert.equal(ui.elements["a-time"].classList.contains("is-better"), true);
  assert.equal(ui.elements["b-fare"].classList.contains("is-better"), false);
  assert.equal(ui.elements["b-time"].classList.contains("is-better"), false);
});

test("different winners for fare and time get one clause each", async () => {
  const ui = setup({ stats: { 1: enough("21.00", 14.0), 2: enough("20.00", 16.0) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("compare-marks"), "B is cheaper by $1.00. A is faster by 2.0 min.");
  assert.equal(ui.elements["b-fare"].classList.contains("is-better"), true);
  assert.equal(ui.elements["a-time"].classList.contains("is-better"), true);
  assert.equal(ui.elements["a-fare"].classList.contains("is-better"), false);
  assert.equal(ui.elements["b-time"].classList.contains("is-better"), false);
});

test("values equal at the shown precision are a tie, with no highlight", async () => {
  const ui = setup({ stats: { 1: enough("20.00", 12.04), 2: enough("20.00", 11.96) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("a-time"), "12.0 min");
  assert.equal(ui.text("b-time"), "12.0 min");
  assert.equal(ui.text("compare-marks"), "Same typical fare. Same typical time.");
  for (const id of ["a-fare", "a-time", "b-fare", "b-time"]) {
    assert.equal(ui.elements[id].classList.contains("is-better"), false);
  }
});

test("a column with fewer than 5 trips shows Not enough data on its own", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: tooFew(3) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("a-fare-avg"), "$12.30");
  assert.equal(ui.text("a-time"), "10.0 min");
  assert.equal(ui.text("b-fare-avg"), "Not enough data");
  assert.equal(ui.text("b-fare-range"), "");
  assert.equal(ui.text("b-time"), "Not enough data");
  assert.equal(ui.text("b-trips"), "3 trips");
  assert.equal(ui.text("compare-marks"), "Can't compare: B has fewer than 5 trips at this hour.");
  for (const id of ["a-fare", "a-time", "b-fare", "b-time"]) {
    assert.equal(ui.elements[id].classList.contains("is-better"), false);
  }
});

test("both columns short of trips, and a single trip", async () => {
  const ui = setup({ stats: { 1: tooFew(1), 2: tooFew(0) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("a-trips"), "1 trip");
  assert.equal(ui.text("b-trips"), "0 trips");
  assert.equal(ui.text("compare-marks"), "Can't compare: A and B have fewer than 5 trips at this hour.");
});

test("a failed column says so and is not compared", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: "error" } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("b-fare-avg"), "Could not load");
  assert.equal(ui.text("a-fare-avg"), "$12.30");
  assert.equal(ui.text("compare-marks"), "");
});

test("changing the day recolours the map and updates both columns together", async () => {
  const byDay = (cheap, dear) => day => (day === 2 ? enough(cheap, 9) : enough(dear, 30));
  const ui = setup({ stats: { 1: byDay("10.00", "50.00"), 2: byDay("40.00", "20.00") } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("compare-marks"), "B is cheaper by $30.00. Same typical time.");
  const heatmapCalls = ui.requests.filter(url => url.endsWith("/heatmap")).length;

  await ui.changeDay(2);
  assert.ok(ui.requests.includes("/api/zones?day=2&hour=17"));
  assert.deepEqual(ui.routeRequests().slice(-2).sort(), [
    "/api/routes?from=1&day=2&hour=17",
    "/api/routes?from=2&day=2&hour=17",
  ]);
  assert.equal(ui.text("compare-when"), "Wednesday 17:00–17:59");
  assert.equal(ui.text("filter-status"), "Showing Wednesday 17:00–17:59");
  assert.equal(ui.text("compare-marks"), "A is cheaper by $30.00. Same typical time.");
  // The heatmaps already cover the whole week: no new request.
  assert.equal(ui.requests.filter(url => url.endsWith("/heatmap")).length, heatmapCalls);
});

test("a stale column response is ignored", async () => {
  let answer = "hold";
  const ui = setup({ stats: { 1: () => answer } });
  await ui.ready();
  await ui.click(1);
  assert.equal(ui.text("a-fare-avg"), "Loading…");
  answer = enough("33.00", 15);
  await ui.changeDay(2);
  assert.equal(ui.text("a-fare-avg"), "$33.00");

  ui.held[0].resolve({ ok: true, status: 200, json: async () => enough("99.00", 50) });
  await settle();
  assert.equal(ui.text("a-fare-avg"), "$33.00");
});

test("weekly pattern: closed by default, opens and closes with one click", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10) } });
  await ui.ready();
  assert.equal(ui.elements["weekly-strip"].hidden, true);

  await ui.press("weekly-toggle");
  assert.equal(ui.elements["weekly-strip"].hidden, false);
  assert.equal(ui.text("weekly-toggle"), "Hide weekly pattern");
  assert.equal(ui.elements["weekly-toggle"].attributes["aria-expanded"], "true");
  assert.equal(ui.body.classList.contains("weekly-open"), true);
  // The map legend moves up above the strip.
  assert.equal(ui.body.style["--weekly-height"], "240px");

  await ui.press("weekly-toggle");
  assert.equal(ui.elements["weekly-strip"].hidden, true);
  assert.equal(ui.text("weekly-toggle"), "Show weekly pattern");
  assert.equal(ui.body.classList.contains("weekly-open"), false);
  assert.equal(ui.body.style["--weekly-height"], "0px");

  await ui.press("weekly-toggle");
  await ui.press("weekly-close");
  assert.equal(ui.elements["weekly-strip"].hidden, true);
});

test("weekly pattern: both heatmaps share one colour scale and outline the selected hour", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) },
    heatmaps: {
      1: heatmapWith({ "0,8": { trip_count: 10, avg_duration_min: 8 }, "0,9": { trip_count: 30, avg_duration_min: 12 } }),
      2: heatmapWith({ "0,9": { trip_count: 110, avg_duration_min: 30 } }),
    },
  });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  await ui.press("weekly-toggle");

  assert.equal(ui.text("weekly-a-title"), "A: Astoria (Queens)");
  assert.equal(ui.text("weekly-b-title"), "B: Midtown Center (Manhattan)");
  // Shared scale 10..110: A's 30 trips is 0.2, B's 110 is the top.
  assert.equal(ui.cell("a", 0, 9).style.backgroundColor, "rgb(51, 50, 204)");
  assert.equal(ui.cell("b", 0, 9).style.backgroundColor, "rgb(255, 50, 0)");
  assert.equal(ui.cell("a", 1, 17).classList.contains("is-selected"), true);
  assert.equal(ui.cell("b", 1, 17).classList.contains("is-selected"), true);

  await ui.changeDay(4);
  assert.equal(ui.cell("a", 1, 17).classList.contains("is-selected"), false);
  assert.equal(ui.cell("a", 4, 17).classList.contains("is-selected"), true);
  assert.equal(ui.cell("b", 4, 17).classList.contains("is-selected"), true);

  // One toggle switches both to average time, still on a shared scale (8..30).
  ui.metric.value = "avg_duration_min";
  ui.metric.listeners.change();
  assert.equal(ui.cell("a", 0, 8).style.backgroundColor, "rgb(0, 50, 255)");
  assert.equal(ui.cell("b", 0, 9).style.backgroundColor, "rgb(255, 50, 0)");
  assert.match(ui.cell("a", 0, 9).title, /12\.0 min/);
});

test("weekly pattern: a zone with no trips at all says so instead of an empty grid", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10), 2: tooFew(0) },
    heatmaps: { 1: heatmapWith({ "0,9": { trip_count: 30, avg_duration_min: 12 } }) },
  });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  await ui.press("weekly-toggle");
  assert.equal(ui.grid("a").className, "heatmap-grid");
  assert.equal(ui.grid("b").textContent, "No trips recorded");
});

test("weekly pattern before both zones are picked", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10) },
    heatmaps: { 1: heatmapWith({ "0,9": { trip_count: 30, avg_duration_min: 12 } }) },
  });
  await ui.ready();
  await ui.press("weekly-toggle");
  assert.equal(ui.grid("a").textContent, "Pick zone A on the map");
  await ui.click(1);
  assert.equal(ui.grid("a").className, "heatmap-grid");
  assert.equal(ui.grid("b").textContent, "Pick zone B on the map");
});

// ---- Added beyond the acceptance criteria (Step 2) ----

test("weekly pattern: the colour key names the metric and the shared scale", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10) } });
  await ui.ready();
  await ui.press("weekly-toggle");
  assert.equal(ui.text("weekly-key-low"), "Fewer");
  assert.equal(ui.text("weekly-key-high"), "more trips");
  ui.metric.value = "avg_duration_min";
  ui.metric.listeners.change();
  assert.equal(ui.text("weekly-key-low"), "Shorter");
  assert.equal(ui.text("weekly-key-high"), "longer avg time");
});

test("address: every pick, clear and filter change is written with replaceState", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  assert.equal(ui.addresses.at(-1), "/compare/?a=1&day=1&hour=17");
  await ui.click(2);
  assert.equal(ui.addresses.at(-1), "/compare/?a=1&b=2&day=1&hour=17");
  await ui.changeDay(2);
  assert.equal(ui.addresses.at(-1), "/compare/?a=1&b=2&day=2&hour=17");
  await ui.press("clear-a");
  assert.equal(ui.addresses.at(-1), "/compare/?b=2&day=2&hour=17");
});

test("address: zones from the link are picked once the map is ready", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) },
    start: { a: 1, b: 2, message: "A zone in the link isn't on the map, so it was left out." },
  });
  await ui.ready();
  assert.equal(ui.text("compare-a-zone"), "Astoria (Queens)");
  assert.equal(ui.text("compare-b-zone"), "Midtown Center (Manhattan)");
  assert.equal(ui.text("compare-marks"), "A is cheaper by $48.20 and faster by 22.8 min.");
  // The server's message about the link stays until the rider picks.
  assert.equal(ui.text("compare-message"), "A zone in the link isn't on the map, so it was left out.");
  // Same time as the map loaded: no second /api/zones request.
  assert.equal(ui.requests.filter(url => url.startsWith("/api/zones?")).length, 0);
});

test("address: a day and hour other than now load once, with Updating…", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10) },
    start: { a: 1, day: 3, hour: 9 },
  });
  // map.js always loads the current time (here Tuesday 17:00).
  ui.ready(1, 17);
  assert.equal(ui.text("filter-status"), "Updating…");
  await settle();
  assert.ok(ui.requests.includes("/api/zones?day=3&hour=9"));
  assert.deepEqual(ui.routeRequests(), ["/api/routes?from=1&day=3&hour=9"]);
  assert.equal(ui.text("filter-status"), "Showing Thursday 9:00–9:59");
  assert.equal(ui.text("compare-when"), "Thursday 9:00–9:59");
  assert.equal(ui.addresses.at(-1), "/compare/?a=1&day=3&hour=9");
});

test("address: if that load fails, the map's time is kept and the columns still load", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10) },
    start: { a: 1, day: 3, hour: 9 },
    zonesFail: true,
  });
  await ui.ready(1, 17);
  assert.equal(ui.elements["day-filter"].value, 1);
  assert.equal(ui.text("filter-status"), "Update failed; showing Tuesday 17:00–17:59");
  assert.deepEqual(ui.routeRequests(), ["/api/routes?from=1&day=1&hour=17"]);
  assert.equal(ui.text("a-fare-avg"), "$12.30");
});

test("choose from list sets that side and resets the list", async () => {
  const ui = setup({ stats: { 3: enough("30.00", 20), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.choose("b", 2);
  assert.equal(ui.text("compare-b-zone"), "Midtown Center (Manhattan)");
  assert.equal(ui.text("compare-a-zone"), "Click a zone on the map to set A");
  assert.equal(ui.elements["b-choose"].value, "");
  await ui.choose("a", 3);
  assert.equal(ui.text("compare-a-zone"), "Harlem (Manhattan)");
  await ui.choose("a", 1);
  assert.equal(ui.text("compare-a-zone"), "Astoria (Queens)");
});

test("choosing the zone already picked for the other side shows a message", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.choose("b", 1);
  assert.equal(ui.text("compare-message"), "That zone is already A. Pick a different zone for B.");
  assert.equal(ui.text("compare-b-zone"), "Click a second zone");
  await ui.choose("b", 2);
  assert.equal(ui.text("compare-message"), "");
});

test("Swap A ↔ B swaps zones, outlines and columns without new requests", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  assert.equal(ui.elements["swap-zones"].hidden, true);
  await ui.click(2);
  assert.equal(ui.elements["swap-zones"].hidden, false);
  const before = ui.requests.length;

  await ui.press("swap-zones");
  assert.equal(ui.requests.length, before);
  assert.equal(ui.text("compare-a-zone"), "Midtown Center (Manhattan)");
  assert.equal(ui.text("compare-b-zone"), "Astoria (Queens)");
  assert.equal(ui.text("a-fare-avg"), "$60.50");
  assert.equal(ui.text("b-fare-avg"), "$12.30");
  assert.equal(ui.styles[2].color, "#0057b8");
  assert.equal(ui.styles[1].color, "#00804a");
  assert.equal(ui.text("compare-marks"), "B is cheaper by $48.20 and faster by 22.8 min.");
  assert.equal(ui.addresses.at(-1), "/compare/?a=2&b=1&day=1&hour=17");
  const live = ui.markers.filter(m => !m.removed);
  assert.equal(live.find(m => m.options.icon.html === "A").options.icon.className.includes("-a"), true);
});

test("Swap while a column is loading ignores the old response and reloads", async () => {
  let answer = "hold";
  const ui = setup({ stats: { 1: () => answer, 2: enough("60.50", 32.8) } });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  answer = enough("12.30", 10);
  await ui.press("swap-zones");
  assert.equal(ui.routeRequests().at(-1), "/api/routes?from=1&day=1&hour=17");
  assert.equal(ui.text("b-fare-avg"), "$12.30");
  ui.held[0].resolve({ ok: true, status: 200, json: async () => enough("99.00", 50) });
  await settle();
  assert.equal(ui.text("a-fare-avg"), "$60.50");
  assert.equal(ui.text("b-fare-avg"), "$12.30");
});

test("busiest hour: most trips on the selected day, earlier hour on a tie", async () => {
  const ui = setup({
    stats: { 1: enough("12.30", 10), 2: enough("60.50", 32.8) },
    heatmaps: {
      1: heatmapWith({
        "1,8": { trip_count: 30, avg_duration_min: 9 },
        "1,17": { trip_count: 30, avg_duration_min: 14 },
        "1,18": { trip_count: 12, avg_duration_min: 15 },
        "2,20": { trip_count: 50, avg_duration_min: 11 },
      }),
      // B's busiest hour on Tuesday has 4 trips: under MIN_TRIP_COUNT.
      2: heatmapWith({ "1,9": { trip_count: 4, avg_duration_min: 9 }, "2,9": { trip_count: 5, avg_duration_min: 9 } }),
    },
  });
  await ui.ready();
  await ui.click(1);
  await ui.click(2);
  assert.equal(ui.text("a-busiest"), "8:00–8:59");
  assert.equal(ui.text("b-busiest"), "Not enough data");

  const before = ui.requests.filter(url => url.endsWith("/heatmap")).length;
  await ui.changeDay(2);
  assert.equal(ui.text("a-busiest"), "20:00–20:59");
  assert.equal(ui.text("b-busiest"), "9:00–9:59");
  assert.equal(ui.requests.filter(url => url.endsWith("/heatmap")).length, before);
});

test("busiest hour with no zone, and for a zone with no trips", async () => {
  const ui = setup({ stats: { 1: enough("12.30", 10) } });
  await ui.ready();
  assert.equal(ui.text("a-busiest"), "—");
  // Zone 1's heatmap answers with an empty grid.
  await ui.click(1);
  assert.equal(ui.text("a-busiest"), "Not enough data");
  assert.equal(ui.text("b-busiest"), "—");
});
