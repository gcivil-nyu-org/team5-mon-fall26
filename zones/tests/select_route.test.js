// US19 #48: taxiscope:select-route sets a new pickup and keeps the dropoff.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const jsRoot = path.join(__dirname, "../static/zones/js");
const sources = ["filters.js", "trip-summary.js", "fare.js", "windows.js"].map(name =>
  fs.readFileSync(path.join(jsRoot, name), "utf8")
);
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const elements = {};
  const listeners = {};
  const dispatched = [];
  const errors = [];
  const requests = [];
  const styled = [];
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
      value: "", textContent: "", attributes: {}, listeners: {},
      classList: { toggle() {} },
      addEventListener(name, fn) { this.listeners[name] = fn; },
      setAttribute(name, value) { this.attributes[name] = value; },
    };
  }
  const body = { dataset: {}, classList: { add() {}, remove() {} } };
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
  const zones = {};
  function zone(id, name) {
    zones[id] = {
      feature: { properties: { zone_id: id, name, borough: "Manhattan", trip_count: 20 } },
      listeners: {},
      on(name, fn) { this.listeners[name] = fn; },
      bringToFront() {}, setTooltipContent() {},
    };
    return zones[id];
  }
  const layer = {
    options: {},
    setStyle(style) { styled.push(style); },
    eachLayer(fn) {
      [zone(161, "Midtown Center"), zone(164, "Midtown South"), zone(132, "JFK Airport")]
        .forEach(fn);
    },
  };
  document.dispatchEvent(new context.CustomEvent("taxiscope:map-ready", {
    detail: {
      map: { createPane() { return { style: {} }; } },
      layer,
      legend: {},
      data: { day: 4, hour: 17, features: [] },
    },
  }));
  return {
    elements, dispatched, errors, requests, styled, zones,
    selectRoute(pickup, dropoff) {
      document.dispatchEvent(
        new context.CustomEvent("taxiscope:select-route", { detail: { pickup, dropoff } })
      );
    },
    selections() {
      return dispatched.filter(event => event.type === "taxiscope:zones-selected");
    },
  };
}

test("select-route sets the pickup, keeps the dropoff and sends zones-selected", () => {
  const ui = setup();
  ui.zones[161].listeners.click();
  ui.zones[132].listeners.click();
  const styledBefore = ui.styled.length;
  ui.selectRoute(164, 132);
  const last = ui.selections().at(-1);
  assert.deepEqual({ ...last.detail }, { pickup: 164, dropoff: 132 });
  assert.equal(ui.elements["pickup-zone"].textContent, "Midtown South (Manhattan)");
  assert.equal(ui.elements["dropoff-zone"].textContent, "JFK Airport (Manhattan)");
  assert.ok(ui.styled.length > styledBefore, "the map is restyled");
  assert.deepEqual(ui.errors, []);
});

test("summary route label and fare request use the new pickup", async () => {
  const ui = setup();
  ui.zones[161].listeners.click();
  ui.zones[132].listeners.click();
  ui.requests.length = 0;
  ui.selectRoute(164, 132);
  await settle();
  assert.match(ui.elements["summary-route"].textContent, /Midtown South.*JFK Airport/);
  assert.ok(ui.requests.some(url => /^\/api\/routes\?/.test(url) && /from=164/.test(url)
    && /to=132/.test(url)));
  assert.ok(ui.requests.some(url => /^\/api\/routes\/windows\?/.test(url)
    && /from=164/.test(url)));
});

test("an unknown zone shows an error and changes nothing", () => {
  const ui = setup();
  ui.zones[161].listeners.click();
  ui.zones[132].listeners.click();
  const count = ui.selections().length;
  ui.selectRoute(999, 132);
  assert.equal(ui.selections().length, count);
  assert.equal(ui.elements["pickup-zone"].textContent, "Midtown Center (Manhattan)");
  assert.deepEqual(ui.errors, ["This zone is unavailable."]);
});
