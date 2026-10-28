const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const jsRoot = path.join(__dirname, "../static/zones/js");
const sources = ["filters.js", "trip-summary.js", "fare.js", "windows.js"].map(name =>
  fs.readFileSync(path.join(jsRoot, name), "utf8")
);

function setup(savedPickup, savedDropoff) {
  const elements = {};
  const listeners = {};
  const dispatched = [];
  const errors = [];
  const requests = [];
  const ids = [
    "day-filter", "hour-filter", "hour-value", "filter-status",
    "pickup-zone", "dropoff-zone", "clear-pickup", "clear-dropoff",
    "clear-selection", "same-zone-trip", "summary-panel",
    "summary-toggle", "summary-route", "summary-time", "fare-range",
    "trip-duration", "best-row", "worst-row", "best-fare",
    "best-duration", "worst-fare", "worst-duration", "windows-status",
  ];
  for (const id of ids) {
    elements[id] = {
      hidden: id === "summary-panel",
      value: "", textContent: "", attributes: {},
      classList: { toggle() {} },
      addEventListener() {},
      setAttribute(name, value) { this.attributes[name] = value; },
    };
  }
  const body = { dataset: {}, classList: { add() {}, remove() {} } };
  if (savedPickup != null) body.dataset.savedPickup = String(savedPickup);
  if (savedDropoff != null) body.dataset.savedDropoff = String(savedDropoff);
  const document = {
    body,
    getElementById(id) { return elements[id]; },
    addEventListener(name, fn) { (listeners[name] ??= []).push(fn); },
    dispatchEvent(event) {
      dispatched.push(event);
      for (const listener of listeners[event.type] ?? []) listener(event);
    },
  };
  const context = {
    document,
    CustomEvent: class {
      constructor(type, options) { this.type = type; this.detail = options.detail; }
    },
    computeBreaks() { return []; },
    colorFor() { return "#fff"; },
    showError(message) { errors.push(message); },
    fetch(url) {
      requests.push(url);
      const slot = { hour: 9, fare_avg: "20.00", avg_duration_min: 10 };
      return Promise.resolve({
        ok: true,
        json: async () => url.startsWith("/api/routes/windows")
          ? { enough_data: true, best: { fare: slot, duration: slot },
            worst: { fare: slot, duration: slot } }
          : { enough_data: true, fare_min: "10.00", fare_avg: "20.00",
            fare_max: "30.00", avg_duration_min: 10 },
      });
    },
    URLSearchParams,
    console: { error() {} },
    DAYS: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    L: { geoJSON() { return { addTo() { return { remove() {} }; } }; } },
    window: { clearTimeout() {}, setTimeout() {} },
  };
  for (const source of sources) vm.runInNewContext(source, context);
  function zone(id, name) {
    return {
      feature: { properties: { zone_id: id, name, borough: "NYC", trip_count: 20 } },
      on() {}, bringToFront() {}, setTooltipContent() {},
    };
  }
  const layer = {
    options: {},
    setStyle() {},
    eachLayer(fn) { [zone(1, "Office"), zone(2, "Home")].forEach(fn); },
  };
  document.dispatchEvent(new context.CustomEvent("taxiscope:map-ready", {
    detail: {
      map: { createPane() { return { style: {} }; } },
      layer,
      legend: {},
      data: { day: 1, hour: 9, features: [
        { properties: { trip_count: 20 } }, { properties: { trip_count: 20 } },
      ] },
    },
  }));
  return { elements, dispatched, errors, requests };
}

test("opening a saved route selects both zones and loads its trip summary", async () => {
  const ui = setup(1, 2);
  await new Promise(resolve => setImmediate(resolve));
  const selection = ui.dispatched.find(event => event.type === "taxiscope:zones-selected");
  assert.ok(selection);
  assert.equal(selection.detail.pickup, 1);
  assert.equal(selection.detail.dropoff, 2);
  assert.equal(ui.elements["pickup-zone"].textContent, "Office (NYC)");
  assert.equal(ui.elements["dropoff-zone"].textContent, "Home (NYC)");
  assert.equal(ui.elements["summary-panel"].hidden, false);
  assert.match(ui.elements["summary-route"].textContent, /Office.*Home/);
  assert.ok(ui.requests.some(url => /\/api\/routes\?/.test(url) && /from=1/.test(url)
    && /to=2/.test(url)));
  assert.ok(ui.requests.some(url => /\/api\/routes\/windows\?/.test(url)
    && /from=1/.test(url) && /to=2/.test(url)));
  assert.match(ui.elements["fare-range"].textContent, /\$20\.00/);
  assert.match(ui.elements["trip-duration"].textContent, /10\.0 min/);
  assert.deepEqual(ui.errors, []);
});

test("a saved trip within one zone also opens its summary", () => {
  const ui = setup(1, 1);
  assert.equal(ui.elements["summary-panel"].hidden, false);
  assert.match(ui.elements["summary-route"].textContent, /Trips within this zone/);
});

test("ordinary map loads without a route selection", () => {
  const ui = setup(null, null);
  assert.equal(
    ui.dispatched.filter(event => event.type === "taxiscope:zones-selected").length,
    0
  );
  assert.equal(ui.elements["summary-panel"].hidden, true);
});

test("a missing zone does not open the wrong route", () => {
  const ui = setup(1, 999);
  assert.equal(ui.elements["summary-panel"].hidden, true);
  assert.equal(ui.errors.length, 1);
});
