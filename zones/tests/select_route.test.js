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
    querySelector() { return null; },
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
    addLegend() { return {}; },
    colorFor() { return "#fff"; },
    showError(message) { errors.push(message); },
    fetch(url) {
      requests.push(url);
      if (url.startsWith("/api/zones?")) {
        const params = new URLSearchParams(url.split("?")[1]);
        return Promise.resolve({
          ok: true,
          json: async () => ({
            day: Number(params.get("day")), hour: Number(params.get("hour")), features: [],
          }),
        });
      }
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
      map: { createPane() { return { style: {} }; }, removeControl() {} },
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
    send(type, detail) {
      document.dispatchEvent(new context.CustomEvent(type, { detail }));
    },
    sent(type) {
      return dispatched.filter(event => event.type === type).map(event => ({ ...event.detail }));
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

// US20 #49: the day plan builder makes the last stop the next pickup.
test("select-route with a null dropoff sets the pickup and clears the dropoff", () => {
  const ui = setup();
  ui.zones[161].listeners.click();
  ui.zones[132].listeners.click();
  ui.selectRoute(164, null);
  assert.deepEqual({ ...ui.selections().at(-1).detail }, { pickup: 164, dropoff: null });
  assert.equal(ui.elements["pickup-zone"].textContent, "Midtown South (Manhattan)");
  assert.equal(ui.elements["dropoff-zone"].textContent, "Click another zone (optional)");
  assert.deepEqual(ui.errors, []);
});

test("select-route with a null dropoff still rejects an unknown pickup", () => {
  const ui = setup();
  ui.selectRoute(999, null);
  assert.equal(ui.selections().length, 0);
  assert.deepEqual(ui.errors, ["This zone is unavailable."]);
});

// US20 #49: the day plan builder moves the header filters with taxiscope:set-time.
test("set-time moves the day and hour filters and reloads the map", async () => {
  const ui = setup();
  ui.requests.length = 0;
  ui.send("taxiscope:set-time", { day: 5, hour: 14 });
  assert.equal(Number(ui.elements["day-filter"].value), 5);
  assert.equal(Number(ui.elements["hour-filter"].value), 14);
  assert.equal(ui.elements["hour-value"].textContent, "14:00–14:59");
  assert.deepEqual(ui.requests, ["/api/zones?day=5&hour=14"]);
  await settle();
  assert.deepEqual(ui.sent("taxiscope:time-changed").at(-1), { day: 5, hour: 14 });
});

test("set-time with only an hour keeps the day", async () => {
  const ui = setup();
  ui.send("taxiscope:set-time", { hour: 9 });
  assert.equal(Number(ui.elements["day-filter"].value), 4);
  assert.equal(ui.requests.at(-1), "/api/zones?day=4&hour=9");
  await settle();
  assert.deepEqual(ui.sent("taxiscope:time-changed").at(-1), { day: 4, hour: 9 });
});

test("set-time to the time already shown does not reload", () => {
  const ui = setup();
  ui.requests.length = 0;
  ui.send("taxiscope:set-time", { day: 4, hour: 17 });
  assert.deepEqual(ui.requests, []);
});

// US20 #49: while "+ Add stop" is armed, a map click picks a stop instead.
test("while a stop is being picked, a map click sends stop-picked and keeps the selection", () => {
  const ui = setup();
  ui.zones[161].listeners.click();
  ui.zones[132].listeners.click();
  const count = ui.selections().length;
  ui.send("taxiscope:stop-picking", { active: true });
  ui.zones[164].listeners.click();
  assert.deepEqual(ui.sent("taxiscope:stop-picked"), [{ zone: 164 }]);
  assert.equal(ui.selections().length, count);
  assert.equal(ui.elements["dropoff-zone"].textContent, "JFK Airport (Manhattan)");
});

test("after picking ends, map clicks select zones as before", () => {
  const ui = setup();
  ui.send("taxiscope:stop-picking", { active: true });
  ui.send("taxiscope:stop-picking", { active: false });
  ui.zones[161].listeners.click();
  assert.deepEqual(ui.sent("taxiscope:stop-picked"), []);
  assert.deepEqual({ ...ui.selections().at(-1).detail }, { pickup: 161, dropoff: null });
});
