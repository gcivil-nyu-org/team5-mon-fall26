const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../routes/static/routes/js/leave-by.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });

function setup(fetch) {
  const ids = [
    "leave-by-panel", "leave-by-form", "leave-by-day", "leave-by-arrive",
    "leave-by-status", "leave-by-result", "leave-by-time",
    "leave-by-duration", "leave-by-fare",
  ];
  const elements = Object.fromEntries(ids.map(id => [id, {
    hidden: true, value: "", textContent: "", listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    checkValidity() { return this.valid !== false; },
  }]));
  const listeners = {};
  const document = {
    getElementById(id) { return elements[id]; },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
  };
  vm.runInNewContext(source, { document, fetch, URLSearchParams, Number, String, Promise, Error });
  return {
    elements,
    emit(name, detail) { for (const callback of listeners[name] || []) callback({ detail }); },
    submit() { elements["leave-by-form"].listeners.submit({ preventDefault() {} }); },
  };
}

test("shows the form for a route and the previous-day estimate", async () => {
  const urls = [];
  const ui = setup(url => {
    urls.push(url);
    return response({
      enough_data: true, leave_day: 0, leave: "23:45",
      avg_duration_min: 45, fare_avg: "18.75",
    });
  });
  ui.emit("taxiscope:map-ready", { data: { day: 1, hour: 0 } });
  assert.equal(ui.elements["leave-by-day"].value, "1");
  assert.equal(ui.elements["leave-by-arrive"].value, "00:00");
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: null });
  assert.equal(ui.elements["leave-by-panel"].hidden, true);
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  assert.equal(ui.elements["leave-by-panel"].hidden, false);
  ui.elements["leave-by-arrive"].value = "00:30";
  ui.submit();
  await settle();
  assert.match(urls[0], /from=1&to=2&day=1&arrive=00%3A30/);
  assert.equal(ui.elements["leave-by-time"].textContent, "Monday 23:45");
  assert.equal(ui.elements["leave-by-duration"].textContent, "45.0 min");
  assert.equal(ui.elements["leave-by-fare"].textContent, "$18.75");
  assert.equal(ui.elements["leave-by-result"].hidden, false);
});

test("shows insufficient data and leaves the estimate hidden", async () => {
  const ui = setup(() => response({ enough_data: false }));
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.submit();
  await settle();
  assert.equal(ui.elements["leave-by-status"].textContent, "Not enough data");
  assert.equal(ui.elements["leave-by-result"].hidden, true);
});

test("changing the route ignores an older response and clears the result", async () => {
  let complete;
  const ui = setup(() => new Promise(resolve => { complete = resolve; }));
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.submit();
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: null });
  complete({ ok: true, json: () => Promise.resolve({ enough_data: true, leave_day: 0, leave: "09:00" }) });
  await settle();
  assert.equal(ui.elements["leave-by-panel"].hidden, true);
  assert.equal(ui.elements["leave-by-result"].hidden, true);
  assert.equal(ui.elements["leave-by-status"].textContent, "");
});

test("changing arrival time clears the estimate and ignores an older response", async () => {
  let complete;
  const ui = setup(() => new Promise(resolve => { complete = resolve; }));
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.submit();
  ui.elements["leave-by-arrive"].value = "10:00";
  ui.elements["leave-by-arrive"].listeners.input();
  complete({ ok: true, json: () => Promise.resolve({ enough_data: true, leave_day: 0, leave: "09:00" }) });
  await settle();
  assert.equal(ui.elements["leave-by-result"].hidden, true);
  assert.equal(ui.elements["leave-by-status"].textContent, "");
});

test("invalid form and failed request never show an estimate", async () => {
  let calls = 0;
  const ui = setup(() => {
    calls += 1;
    return Promise.resolve({ ok: false, status: 500 });
  });
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.elements["leave-by-form"].valid = false;
  ui.submit();
  assert.equal(calls, 0);
  ui.elements["leave-by-form"].valid = true;
  ui.submit();
  await settle();
  assert.equal(ui.elements["leave-by-status"].textContent, "Could not load leave-by estimate");
  assert.equal(ui.elements["leave-by-result"].hidden, true);
});
