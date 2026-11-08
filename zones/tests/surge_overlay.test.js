// US29 #76: the "Show likely surge hours" overlay on the map's heatmap.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/zones/js/heatmap.js"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));
const ok = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });

function fakeElement(tag) {
  const element = {
    tagName: tag, className: "", title: "", textContent: "", hidden: false, checked: false,
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

function emptyGrid(fill) {
  return Array.from({ length: 7 }, () => Array.from({ length: 24 }, fill));
}

function heatmapFor(zoneId) {
  const heatmap = emptyGrid(() => ({ trip_count: 10, avg_duration_min: 12 }));
  return { zone_id: zoneId, zone_name: "Zone", borough: "Manhattan", heatmap };
}

function surgeFor(zoneId, marked = [[4, 18]]) {
  const surge = emptyGrid(() => ({
    trip_count: 50, fare_per_mile: "8.00", avg_wait_min: 4.0, surge_ratio: 1.0, likely_surge: false,
  }));
  for (const [day, hour] of marked) {
    surge[day][hour] = {
      trip_count: 60, fare_per_mile: "10.40", avg_wait_min: 7.25, surge_ratio: 1.3, likely_surge: true,
    };
  }
  // Too few trips: never marked by the API.
  surge[5][2] = { trip_count: 4, fare_per_mile: null, avg_wait_min: null, surge_ratio: null, likely_surge: false };
  return {
    zone_id: zoneId, zone_name: "Zone", borough: "Manhattan", enough_data: true,
    median_fare_per_mile: "8.00", surge_ratio_threshold: 1.25, min_trip_count: 5, surge,
  };
}

function setup(answer) {
  const elements = {};
  for (const id of ["heatmap-panel", "heatmap-title", "heatmap-container", "pickup-zone",
    "surge-toggle", "surge-legend", "surge-status"]) {
    elements[id] = fakeElement("div");
  }
  elements["heatmap-panel"].hidden = true;
  elements["surge-legend"].hidden = true;
  const listeners = {};
  const requests = [];
  const context = {
    console: { error() {} },
    document: {
      getElementById(id) { return elements[id] ?? null; },
      createElement: fakeElement,
      querySelectorAll() { return []; },
      querySelector() { return { value: "trip_count" }; },
      addEventListener(name, fn) { listeners[name] = fn; },
    },
    fetch: url => {
      requests.push(url);
      return answer(url);
    },
  };
  context.window = context;
  vm.runInNewContext(source, context);
  const toggle = elements["surge-toggle"];
  return {
    elements, requests,
    select(pickup) { listeners["taxiscope:zones-selected"]({ detail: { pickup, dropoff: null } }); },
    setOverlay(on) { toggle.checked = on; toggle.listeners.change.call(toggle); },
    cell(day, hour) {
      const grid = elements["heatmap-container"].children[0];
      return grid.children[day + 1].children[hour + 1];
    },
    marked() {
      const grid = elements["heatmap-container"].children[0];
      return grid.children.slice(1).flatMap(row => row.children.filter(c => c.classList.contains("is-surge")));
    },
  };
}

const byUrl = (surge = surgeFor) => url => {
  const id = Number(url.split("/")[3]);
  return url.endsWith("/surge") ? ok(surge(id)) : ok(heatmapFor(id));
};

test("off by default: no surge request and no marks", async () => {
  const ui = setup(byUrl());
  ui.select(161);
  await settle();
  assert.deepEqual(ui.requests, ["/api/zones/161/heatmap"]);
  assert.equal(ui.marked().length, 0);
  assert.equal(ui.elements["surge-legend"].hidden, true);
});

test("turning it on marks the likely surge hours and shows the legend", async () => {
  const ui = setup(byUrl());
  ui.select(161);
  await settle();
  ui.setOverlay(true);
  await settle();
  assert.equal(ui.requests.at(-1), "/api/zones/161/surge");
  assert.equal(ui.elements["surge-legend"].hidden, false);
  assert.deepEqual(ui.marked(), [ui.cell(4, 18)]);
  assert.equal(ui.elements["surge-status"].textContent, "1 likely surge hour this week (typical $8.00 per mile).");
});

test("hovering a marked cell shows its fare per mile and average wait", async () => {
  const ui = setup(byUrl());
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  assert.equal(
    ui.cell(4, 18).title,
    "Fri 18:00\n10\nLikely Uber/Lyft surge: $10.40 per mile (1.30× typical), average wait 7.3 min"
  );
  assert.equal(ui.cell(4, 17).title, "Fri 17:00\n10");
});

test("a marked cell without enough waits says so", async () => {
  const ui = setup(byUrl(id => {
    const data = surgeFor(id);
    data.surge[4][18].avg_wait_min = null;
    return data;
  }));
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  assert.match(ui.cell(4, 18).title, /average wait: not enough data$/);
});

test("cells with too few trips are never marked", async () => {
  const ui = setup(byUrl());
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  assert.equal(ui.cell(5, 2).classList.contains("is-surge"), false);
});

test("turning it off removes the marks and hides the legend", async () => {
  const ui = setup(byUrl());
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  ui.setOverlay(false);
  assert.equal(ui.marked().length, 0);
  assert.equal(ui.elements["surge-legend"].hidden, true);
  // Turning it on again reuses the loaded grid.
  const before = ui.requests.length;
  ui.setOverlay(true);
  assert.equal(ui.requests.length, before);
  assert.equal(ui.marked().length, 1);
});

test("a new zone loads its own surge hours while the overlay is on", async () => {
  const ui = setup(byUrl(id => surgeFor(id, id === 237 ? [[0, 8], [0, 9]] : [[4, 18]])));
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  ui.select(237);
  await settle();
  assert.ok(ui.requests.includes("/api/zones/237/surge"));
  assert.deepEqual(ui.marked(), [ui.cell(0, 8), ui.cell(0, 9)]);
  assert.equal(ui.elements["surge-status"].textContent, "2 likely surge hours this week (typical $8.00 per mile).");
});

test("a late answer for the previous zone is ignored", async () => {
  let release;
  const late = new Promise(resolve => { release = resolve; });
  const ui = setup(url => {
    if (url === "/api/zones/161/surge") return late.then(() => ok(surgeFor(161, [[6, 23]])));
    return byUrl()(url);
  });
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  ui.select(237);
  await settle();
  release();
  await settle();
  await settle();
  assert.deepEqual(ui.marked(), [ui.cell(4, 18)]);
});

test("a zone without enough rideshare data marks nothing and says why", async () => {
  const ui = setup(byUrl(id => ({ ...surgeFor(id, []), enough_data: false, median_fare_per_mile: null })));
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  assert.equal(ui.marked().length, 0);
  assert.equal(
    ui.elements["surge-status"].textContent,
    "Not enough Uber/Lyft trips from this zone to estimate surge hours."
  );
});

test("a failed surge request keeps the heatmap and shows an error", async () => {
  const ui = setup(url => (url.endsWith("/surge") ? Promise.resolve({ ok: false, status: 500 }) : byUrl()(url)));
  ui.select(161);
  ui.setOverlay(true);
  await settle();
  assert.equal(ui.elements["surge-status"].textContent, "Could not load likely surge hours.");
  assert.equal(ui.marked().length, 0);
  assert.equal(ui.elements["heatmap-panel"].hidden, false);
});
