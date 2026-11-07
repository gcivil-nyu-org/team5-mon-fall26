// Run with: node --test zones/tests/route_reports.test.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../reports/static/reports/js/route-reports.js"),
  "utf8"
);

function setup(fetch) {
  const listeners = {};
  const row = { hidden: true };
  const status = {
    textContent: "",
    classes: new Set(),
    classList: {
      add(name) { status.classes.add(name); },
      remove(name) { status.classes.delete(name); },
    },
  };
  const list = {
    children: [],
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  };
  const elements = {
    "rider-reports-row": row,
    "rider-reports-status": status,
    "rider-reports-list": list,
  };
  const document = {
    getElementById(id) { return elements[id]; },
    createElement() { return { textContent: "" }; },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
  };
  vm.runInNewContext(source, {
    document, fetch, URLSearchParams, Number, String, console: { error() {} },
  });
  return {
    row, status, list,
    select(pickup, dropoff) {
      for (const listener of listeners["taxiscope:zones-selected"]) {
        listener({ detail: { pickup, dropoff } });
      }
    },
  };
}

const response = (data) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(data),
});
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("only a selected route loads reports and handles too few", async () => {
  const urls = [];
  const ui = setup((url) => {
    urls.push(url);
    return response({ enough_data: false });
  });
  ui.select(161, null);
  assert.equal(ui.row.hidden, true);
  assert.equal(urls.length, 0);
  ui.select(161, 237);
  await settle();
  assert.equal(ui.row.hidden, false);
  assert.match(urls[0], /from=161&to=237/);
  assert.equal(ui.status.textContent, "Not enough reports yet");
  assert.equal(ui.list.children.length, 0);
});

test("shows medians and five anonymous ride lines", async () => {
  const ui = setup(() => response({
    enough_data: true,
    report_count: 5,
    median_taxi_fare: "20.00",
    rideshare_quote_count: 1,
    median_rideshare_quote: "25.00",
    recent_reports: [
      { ride_day: "2026-11-04", ride_hour: 9, taxi_fare: "21.00",
        rideshare_service: "uber", rideshare_quote: "25.00" },
    ],
  }));
  ui.select(161, 237);
  await settle();
  assert.match(ui.status.textContent, /5 reports; median taxi fare \$20\.00/);
  assert.match(ui.status.textContent, /1 rideshare quotes; median \$25\.00/);
  assert.equal(ui.list.children.length, 1);
  assert.equal(
    ui.list.children[0].textContent,
    "2026-11-04 09:00 - Taxi $21.00; Uber quote $25.00"
  );
});

test("an old response cannot replace a new route or a cleared route", async () => {
  const pending = [];
  const ui = setup(() => new Promise((resolve) => pending.push(resolve)));
  ui.select(161, 237);
  ui.select(161, 132);
  pending[1](response({ enough_data: false }));
  await settle();
  pending[0](response({ enough_data: true, report_count: 99 }));
  await settle();
  assert.equal(ui.status.textContent, "Not enough reports yet");
  ui.select(null, null);
  assert.equal(ui.row.hidden, true);
  assert.equal(ui.status.textContent, "");
});
