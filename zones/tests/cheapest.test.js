// US16 #45: cheapest-in-the-next-3-hours panel.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../routes/static/routes/js/cheapest.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });

function element(extra = {}) {
  return {
    hidden: true, value: "", textContent: "", className: "", listeners: {}, children: [],
    addEventListener(name, callback) { this.listeners[name] = callback; },
    checkValidity() { return this.valid !== false; },
    replaceChildren() { this.children = []; },
    append(...nodes) { this.children.push(...nodes); },
    ...extra,
  };
}

function setup(fetch) {
  const ids = [
    "arrive-by-mode", "cheapest-mode", "cheapest-form", "cheapest-day", "cheapest-start",
    "cheapest-now", "cheapest-status", "cheapest-result", "cheapest-hours", "cheapest-best",
    "cheapest-leave", "cheapest-duration", "cheapest-arrive",
  ];
  const elements = Object.fromEntries(ids.map(id => [id, element()]));
  elements["arrive-by-mode"].hidden = false;
  const modes = [element({ value: "arrive", checked: true }), element({ value: "cheapest", checked: false })];
  const listeners = {};
  const events = [];
  const document = {
    getElementById(id) { return elements[id]; },
    querySelectorAll() { return modes; },
    createElement() { return element(); },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
    dispatchEvent(event) { events.push(event); },
  };
  class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } }
  vm.runInNewContext(source, {
    document, fetch, URLSearchParams, Number, String, Promise, Error, Object, Intl, Date, CustomEvent,
  });
  return {
    elements, modes, events,
    emit(name, detail) { for (const callback of listeners[name] || []) callback({ detail }); },
    submit() { elements["cheapest-form"].listeners.submit({ preventDefault() {} }); },
    rows() {
      return elements["cheapest-hours"].children.map(row => ({
        cls: row.className, hour: row.children[0].textContent, fare: row.children[1].textContent,
      }));
    },
  };
}

const MIDNIGHT = {
  enough_data: true, cheapest: 2,
  hours: [
    { day: 4, hour: 22, enough_data: true, fare_avg: "30.00" },
    { day: 4, hour: 23, enough_data: false, fare_avg: null },
    { day: 5, hour: 0, enough_data: true, fare_avg: "21.00" },
  ],
  leave_day: 5, leave: "00:00", arrive_day: 5, arrive: "00:40", avg_duration_min: 40,
};

test("switching modes shows the cheapest form and hides Arrive by", () => {
  const ui = setup(() => response(MIDNIGHT));
  ui.modes[1].checked = true;
  ui.modes[1].listeners.change();
  assert.equal(ui.elements["cheapest-mode"].hidden, false);
  assert.equal(ui.elements["arrive-by-mode"].hidden, true);
});

test("lists the 3 hours, highlights the cheapest and crosses midnight", async () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(MIDNIGHT); });
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.elements["cheapest-day"].value = "4";
  ui.elements["cheapest-start"].value = "22:00";
  ui.submit();
  await settle();
  assert.equal(urls[0], "/api/routes/cheapest?from=1&to=2&day=4&start=22%3A00");
  assert.deepEqual(ui.rows(), [
    { cls: "", hour: "Fri 22:00–22:59", fare: "$30.00" },
    { cls: "", hour: "Fri 23:00–23:59", fare: "Not enough data" },
    { cls: "is-cheapest", hour: "Sat 00:00–00:59", fare: "$21.00 (cheapest)" },
  ]);
  assert.equal(ui.elements["cheapest-leave"].textContent, "Saturday 00:00");
  assert.equal(ui.elements["cheapest-duration"].textContent, "40.0 min");
  assert.equal(ui.elements["cheapest-arrive"].textContent, "Saturday 00:40");
  assert.equal(ui.elements["cheapest-best"].hidden, false);
});

test("says so when none of the 3 hours has enough trips", async () => {
  const empty = {
    enough_data: false, cheapest: null,
    hours: [0, 1, 2].map(i => ({ day: 0, hour: 8 + i, enough_data: false, fare_avg: null })),
  };
  const ui = setup(() => response(empty));
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.submit();
  await settle();
  assert.equal(ui.elements["cheapest-best"].hidden, true);
  assert.match(ui.elements["cheapest-status"].textContent, /None of these 3 hours has enough past trips/);
  assert.ok(ui.rows().every(row => row.fare === "Not enough data"));
});

test("Now sends the current New York day and exact time", async () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(MIDNIGHT); });
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.elements["cheapest-now"].listeners.click();
  await settle();
  assert.match(urls[0], /day=[0-6]&start=([01]\d|2[0-3])%3A[0-5]\d$/);
  assert.equal(ui.events[0].type, "taxiscope:plan-result");
  assert.equal(ui.events[0].detail.mode, "cheapest");
});

test("does nothing until both zones are selected", () => {
  const urls = [];
  const ui = setup(url => { urls.push(url); return response(MIDNIGHT); });
  ui.submit();
  assert.equal(urls.length, 0);
});
