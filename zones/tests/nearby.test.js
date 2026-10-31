// US19 #48: cheaper adjacent pickup zones in the trip summary.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../routes/static/routes/js/nearby.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });

function element(extra = {}) {
  return {
    hidden: true, textContent: "", className: "", type: "", listeners: {}, children: [],
    attributes: {}, classes: new Set(),
    classList: {
      toggle(name, on) { on ? this.owner.classes.add(name) : this.owner.classes.delete(name); },
    },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    replaceChildren() { this.children = []; },
    append(...nodes) { this.children.push(...nodes); },
    ...extra,
  };
}

function make(extra) {
  const el = element(extra);
  el.classList.owner = el;
  return el;
}

function setup(fetch) {
  const elements = Object.fromEntries(
    ["nearby-panel", "nearby-status", "nearby-list"].map(id => [id, make()])
  );
  const listeners = {};
  const events = [];
  const document = {
    getElementById(id) { return elements[id]; },
    createElement() { return make(); },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
    dispatchEvent(event) { events.push(event); },
  };
  class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } }
  vm.runInNewContext(source, {
    document, fetch, URLSearchParams, Number, Promise, Error, CustomEvent,
  });
  const ui = {
    elements, events,
    emit(name, detail) { for (const callback of listeners[name] || []) callback({ detail }); },
    select(pickup, dropoff) { ui.emit("taxiscope:zones-selected", { pickup, dropoff }); },
    buttons() { return elements["nearby-list"].children.map(item => item.children[0]); },
    status() { return elements["nearby-status"].textContent; },
  };
  ui.emit("taxiscope:map-ready", { data: { day: 4, hour: 17 } });
  return ui;
}

const SUGGESTIONS = {
  from: 161, to: 132, day: 4, hour: 17, enough_data: true, neighbor_count: 5,
  current: { trip_count: 40, fare_avg: "62.10", avg_duration_min: 48.2 },
  suggestions: [
    { zone_id: 164, name: "Midtown South", borough: "Manhattan", trip_count: 22,
      fare_avg: "57.40", avg_duration_min: 45, saving: "4.70" },
    { zone_id: 230, name: "Times Sq/Theatre District", borough: "Manhattan", trip_count: 31,
      fare_avg: "59.90", avg_duration_min: 47.5, saving: "2.20" },
  ],
};

test("requests /api/routes/nearby with from, to, day and hour", async () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(SUGGESTIONS); });
  ui.select(161, 132);
  await settle();
  assert.deepEqual(urls, ["/api/routes/nearby?from=161&to=132&day=4&hour=17"]);
  assert.equal(ui.elements["nearby-panel"].hidden, false);
});

test("renders name, typical fare, saving and journey time in API order", async () => {
  const ui = setup(() => response(SUGGESTIONS));
  ui.select(161, 132);
  await settle();
  assert.deepEqual(ui.buttons().map(button => button.textContent), [
    "Midtown South: $57.40, save $4.70, 45.0 min",
    "Times Sq/Theatre District: $59.90, save $2.20, 47.5 min",
  ]);
  assert.equal(ui.status(), "");
});

test("clicking a suggestion sends select-route with the new pickup and the same dropoff", async () => {
  const ui = setup(() => response(SUGGESTIONS));
  ui.select(161, 132);
  await settle();
  ui.buttons()[0].listeners.click();
  const event = ui.events.find(e => e.type === "taxiscope:select-route");
  assert.deepEqual({ ...event.detail }, { pickup: 164, dropoff: 132 });
});

test("reloads for the new pickup after a suggestion is chosen", async () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(SUGGESTIONS); });
  ui.select(161, 132);
  await settle();
  ui.select(164, 132);
  await settle();
  assert.match(urls.at(-1), /from=164&to=132/);
});

test("says not enough data when the current route has too few trips", async () => {
  const ui = setup(() => response({
    ...SUGGESTIONS, enough_data: false, suggestions: [],
    current: { trip_count: 3, fare_avg: null, avg_duration_min: null },
  }));
  ui.select(161, 132);
  await settle();
  assert.equal(ui.status(), "Not enough past trips on this route to compare nearby zones.");
  assert.equal(ui.buttons().length, 0);
  assert.equal(ui.elements["nearby-panel"].hidden, false);
});

test("says none cheaper instead of an empty list", async () => {
  const ui = setup(() => response({ ...SUGGESTIONS, suggestions: [] }));
  ui.select(161, 132);
  await settle();
  assert.equal(ui.status(), "No adjacent pickup zone is cheaper at this time.");
  assert.equal(ui.buttons().length, 0);
});

test("says so when no zone borders the pickup", async () => {
  const ui = setup(() => response({ ...SUGGESTIONS, neighbor_count: 0, suggestions: [] }));
  ui.select(202, 132);
  await settle();
  assert.equal(ui.status(), "No zones border this pickup zone.");
});

test("no bordering zones wins over not enough data", async () => {
  const ui = setup(() => response({
    ...SUGGESTIONS, enough_data: false, neighbor_count: 0, suggestions: [],
    current: { trip_count: 2, fare_avg: null, avg_duration_min: null },
  }));
  ui.select(202, 132);
  await settle();
  assert.equal(ui.status(), "No zones border this pickup zone.");
  assert.equal(ui.buttons().length, 0);
});

test("shows an error when the request fails", async () => {
  const ui = setup(() => Promise.resolve({ ok: false, status: 500 }));
  ui.select(161, 132);
  await settle();
  assert.equal(ui.status(), "Could not load nearby pickup zones");
  assert.ok(ui.elements["nearby-status"].classes.has("error"));
});

test("hidden until both zones are selected", () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(SUGGESTIONS); });
  ui.select(161, null);
  assert.equal(ui.elements["nearby-panel"].hidden, true);
  assert.equal(urls.length, 0);
});

test("hidden for a trip within one zone", () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(SUGGESTIONS); });
  ui.select(161, 161);
  assert.equal(ui.elements["nearby-panel"].hidden, true);
  assert.equal(urls.length, 0);
});

test("reloads when the hour changes, not when the time is unchanged", async () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(SUGGESTIONS); });
  ui.select(161, 132);
  await settle();
  ui.emit("taxiscope:time-changed", { day: 4, hour: 17 });
  assert.equal(urls.length, 1);
  ui.emit("taxiscope:time-changed", { day: 4, hour: 8 });
  await settle();
  assert.equal(urls.length, 2);
  assert.match(urls[1], /day=4&hour=8$/);
});

test("ignores a stale response", async () => {
  let resolveFirst;
  const replies = [
    new Promise(resolve => { resolveFirst = resolve; }),
    response({ ...SUGGESTIONS, suggestions: [] }),
  ];
  const ui = setup(() => replies.shift());
  ui.select(161, 132);
  ui.select(164, 132);
  await settle();
  resolveFirst({ ok: true, json: () => Promise.resolve(SUGGESTIONS) });
  await settle();
  assert.equal(ui.buttons().length, 0);
  assert.equal(ui.status(), "No adjacent pickup zone is cheaper at this time.");
});
