// US3 #5 + US22 #69: the map's heatmap panel, and the reusable 7x24 grid
// that the compare page draws twice.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/zones/js/heatmap.js"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));

function fakeElement(tag) {
  const element = {
    tagName: tag, className: "", title: "", textContent: "", hidden: false,
    style: {}, children: [], listeners: {},
    classList: {
      add(name) { element.className = `${element.className} ${name}`.trim(); },
      contains(name) { return element.className.split(" ").includes(name); },
    },
    appendChild(child) { element.children.push(child); return child; },
    addEventListener(name, fn) { element.listeners[name] = fn; },
  };
  Object.defineProperty(element, "innerHTML", {
    get() { return element._html ?? ""; },
    set(value) { element._html = value; element.children = []; },
  });
  return element;
}

function sampleHeatmap() {
  // Monday 8:00 = 10 trips, Monday 9:00 = 30 trips, Tuesday 9:00 = 20 trips.
  const heatmap = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => ({ trip_count: null, avg_duration_min: null }))
  );
  heatmap[0][8] = { trip_count: 10, avg_duration_min: 12.25 };
  heatmap[0][9] = { trip_count: 30, avg_duration_min: 20 };
  heatmap[1][9] = { trip_count: 20, avg_duration_min: 16 };
  return { zone_id: 7, zone_name: "Astoria", borough: "Queens", heatmap };
}

function setup({ mapPage = true, data = sampleHeatmap() } = {}) {
  const elements = {};
  if (mapPage) {
    for (const id of ["heatmap-panel", "heatmap-title", "heatmap-container", "pickup-zone"]) {
      elements[id] = fakeElement("div");
    }
    elements["heatmap-panel"].hidden = true;
    elements["pickup-zone"].textContent = "Astoria (Queens)";
  }
  const listeners = {};
  const context = {
    console: { error() {} },
    document: {
      getElementById(id) { return elements[id] ?? null; },
      createElement: fakeElement,
      querySelectorAll() { return []; },
      querySelector() { return { value: "trip_count" }; },
      addEventListener(name, fn) { listeners[name] = fn; },
    },
    fetch: async () => ({ ok: true, json: async () => data }),
  };
  context.window = context;
  vm.runInNewContext(source, context);
  return { elements, listeners, context };
}

const rows = grid => grid.children.slice(1);
const cell = (grid, day, hour) => rows(grid)[day].children[hour + 1];

test("map panel: grid has an hour header and 7 labelled day rows of 24 cells", async () => {
  const ui = setup();
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: 7, dropoff: null } });
  await settle();

  assert.equal(ui.elements["heatmap-panel"].hidden, false);
  assert.equal(ui.elements["heatmap-title"].textContent, "Astoria (Queens) - Weekly Demand");
  const grid = ui.elements["heatmap-container"].children[0];
  assert.equal(grid.className, "heatmap-grid");
  const header = grid.children[0];
  assert.equal(header.className, "heatmap-row heatmap-header");
  assert.equal(header.children.length, 25);
  assert.equal(header.children[1].className, "heatmap-hour-label");
  assert.equal(header.children[24].textContent, 23);
  assert.equal(rows(grid).length, 7);
  assert.equal(rows(grid)[0].children[0].textContent, "Mon");
  assert.equal(rows(grid)[6].children[0].textContent, "Sun");
  assert.equal(rows(grid)[0].children.length, 25);
});

test("map panel: colours scale from the zone's own min (blue) to max (red)", async () => {
  const ui = setup();
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: 7, dropoff: null } });
  await settle();
  const grid = ui.elements["heatmap-container"].children[0];

  assert.equal(cell(grid, 0, 8).style.backgroundColor, "rgb(0, 50, 255)");
  assert.equal(cell(grid, 0, 9).style.backgroundColor, "rgb(255, 50, 0)");
  assert.equal(cell(grid, 1, 9).style.backgroundColor, "rgb(128, 50, 128)");
  assert.equal(cell(grid, 0, 9).title, "Mon 9:00\n30");
  assert.equal(cell(grid, 0, 0).className, "heatmap-cell no-data");
  assert.equal(cell(grid, 0, 0).title, "Mon 0:00 - No data");
});

test("map panel: clearing the pickup hides the panel", async () => {
  const ui = setup();
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: 7, dropoff: null } });
  await settle();
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: null, dropoff: null } });
  assert.equal(ui.elements["heatmap-panel"].hidden, true);
  assert.equal(ui.elements["heatmap-container"].children.length, 0);
});

test("map panel: a failed request shows the error in the visible panel", async () => {
  const ui = setup();
  ui.context.fetch = async () => ({ ok: false });
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: 7, dropoff: null } });
  await settle();
  assert.equal(ui.elements["heatmap-panel"].hidden, false);
  assert.match(ui.elements["heatmap-container"].innerHTML, /Failed to load heatmap data/);
});

test("renderGrid loads on a page without the heatmap panel", () => {
  const ui = setup({ mapPage: false });
  assert.equal(typeof ui.context.TaxiScopeHeatmap.renderGrid, "function");
});

test("renderGrid outlines the highlighted day and hour only", () => {
  const ui = setup({ mapPage: false });
  const container = fakeElement("div");
  ui.context.TaxiScopeHeatmap.renderGrid(container, sampleHeatmap(), "trip_count", {
    highlight: { day: 1, hour: 9 },
  });
  const grid = container.children[0];
  const selected = rows(grid).flatMap(row => row.children.filter(c => c.classList.contains("is-selected")));
  assert.equal(selected.length, 1);
  assert.equal(selected[0], cell(grid, 1, 9));
  // An empty highlighted cell is outlined too.
  ui.context.TaxiScopeHeatmap.renderGrid(container, sampleHeatmap(), "trip_count", {
    highlight: { day: 3, hour: 0 },
  });
  assert.equal(cell(container.children[0], 3, 0).classList.contains("is-selected"), true);
});

test("renderGrid uses a shared range when one is given", () => {
  const ui = setup({ mapPage: false });
  const container = fakeElement("div");
  ui.context.TaxiScopeHeatmap.renderGrid(container, sampleHeatmap(), "trip_count", {
    range: { min: 10, max: 110 },
  });
  const grid = container.children[0];
  // 30 trips on a 10..110 scale = intensity 0.2.
  assert.equal(cell(grid, 0, 9).style.backgroundColor, "rgb(51, 50, 204)");
});

test("valueRange gives min and max of a metric, or null without data", () => {
  const ui = setup({ mapPage: false });
  const { valueRange } = ui.context.TaxiScopeHeatmap;
  assert.deepEqual({ ...valueRange(sampleHeatmap(), "trip_count") }, { min: 10, max: 30 });
  assert.deepEqual({ ...valueRange(sampleHeatmap(), "avg_duration_min") }, { min: 12.25, max: 20 });
  const empty = sampleHeatmap();
  empty.heatmap = empty.heatmap.map(day => day.map(() => ({ trip_count: null, avg_duration_min: null })));
  assert.equal(valueRange(empty, "trip_count"), null);
});
