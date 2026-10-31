// US20 #49: drag and drop on the day plan page, with a fake SortableJS.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../routes/static/routes/js/day-plan-sort.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup({ fetch = () => assert.fail("no request expected"), sortable = true, list = true } = {}) {
  const items = ["11", "12", "13"].map(stopId => ({ dataset: { stopId } }));
  const classes = new Set();
  const elements = {
    "day-plan-stops": list ? { children: items, dataset: { reorderUrl: "/day-plans/7/reorder/" } } : null,
    "day-plan-sort-status": {
      textContent: "",
      classList: { add(name) { classes.add(name); }, remove(name) { classes.delete(name); } },
    },
  };
  const requests = [];
  const reloads = [];
  const timers = [];
  const created = [];
  const context = {
    document: {
      getElementById(id) { return elements[id]; },
      querySelector() { return { value: "csrf-test-token" }; },
    },
    window: {
      location: { reload() { reloads.push(true); } },
      setTimeout(callback) { timers.push(callback); },
    },
    fetch(url, options) { requests.push({ url, options }); return fetch(url, options); },
    URLSearchParams, Array, Error, Promise,
  };
  if (sortable) context.Sortable = { create(el, options) { created.push({ el, options }); } };
  vm.runInNewContext(source, context);
  return {
    items, classes, elements, requests, reloads, timers, created,
    // Simulate a drop: reorder the DOM like SortableJS, then call onEnd.
    drop(order, oldIndex = 0, newIndex = 2) {
      items.splice(0, items.length, ...order.map(id => ({ dataset: { stopId: id } })));
      created[0].options.onEnd({ oldIndex, newIndex });
    },
    status() { return elements["day-plan-sort-status"].textContent; },
  };
}

test("makes the stop list sortable by its drag handles", () => {
  const ui = setup();
  assert.equal(ui.created.length, 1);
  assert.equal(ui.created[0].el, ui.elements["day-plan-stops"]);
  assert.equal(ui.created[0].options.handle, ".drag-handle");
});

test("drop posts the new stop order with the CSRF header, then reloads", async () => {
  const ui = setup({ fetch: () => Promise.resolve({ ok: true, json: async () => ({ ok: true }) }) });
  ui.drop(["13", "11", "12"]);
  const { url, options } = ui.requests[0];
  assert.equal(url, "/day-plans/7/reorder/");
  assert.equal(options.method, "POST");
  assert.equal(options.headers["X-CSRFToken"], "csrf-test-token");
  assert.equal(options.body.get("order"), "13,11,12");
  assert.equal(ui.status(), "Saving the new order…");
  await settle();
  assert.equal(ui.reloads.length, 1);
});

test("a drop back in the same place sends nothing", () => {
  const ui = setup();
  ui.drop(["11", "12", "13"], 1, 1);
  assert.equal(ui.requests.length, 0);
});

test("a failed reorder shows the server's message and reloads", async () => {
  const ui = setup({
    fetch: () => Promise.resolve({
      ok: false, json: async () => ({ error: "The stops have changed. Reload the page and try again." }),
    }),
  });
  ui.drop(["13", "11", "12"]);
  await settle();
  assert.equal(ui.status(), "The stops have changed. Reload the page and try again. Reloading…");
  assert.ok(ui.classes.has("error"));
  assert.equal(ui.reloads.length, 0);
  ui.timers[0]();
  assert.equal(ui.reloads.length, 1);
});

test("a network error says so and reloads", async () => {
  const ui = setup({ fetch: () => Promise.reject(new Error("Failed to fetch")) });
  ui.drop(["13", "11", "12"]);
  await settle();
  assert.equal(ui.status(), "Could not save the new order. Check your connection. Reloading…");
  ui.timers[0]();
  assert.equal(ui.reloads.length, 1);
});

test("without SortableJS, or without the list, nothing happens (the buttons still work)", () => {
  assert.equal(setup({ sortable: false }).created.length, 0);
  assert.doesNotThrow(() => setup({ list: false }));
});
