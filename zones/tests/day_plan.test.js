// US20 #49: build a multi-stop day plan on the map.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../routes/static/routes/js/day-plan.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = (status, data) => Promise.resolve({ status, ok: status < 400, json: async () => data });

function element(extra = {}) {
  const el = {
    hidden: false, disabled: false, value: "", textContent: "", type: "", href: "",
    listeners: {}, children: [], attributes: {}, classes: new Set(),
    addEventListener(name, callback) { this.listeners[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    replaceChildren(...nodes) { this.children = nodes; },
    append(...nodes) { this.children.push(...nodes); },
    querySelector() { return { value: "csrf-test-token" }; },
    ...extra,
  };
  el.classList = { toggle(name, on) { on ? el.classes.add(name) : el.classes.delete(name); } };
  return el;
}

const IDS = [
  "day-plan-panel", "day-plan-add", "day-plan-stops", "day-plan-form", "day-plan-day",
  "day-plan-name", "day-plan-save", "day-plan-clear", "day-plan-status", "day-plan-open",
  "day-plan-signin",
];
const NAMES = { 33: "Brooklyn Heights", 161: "Midtown Center", 230: "Times Sq", 12: "Battery Park" };

function setup({ fetch = () => assert.fail("no request expected"), guest = false } = {}) {
  const elements = Object.fromEntries(IDS.map(id => [id, element()]));
  elements["day-plan-panel"].hidden = true;
  elements["day-plan-open"].hidden = true;
  elements["day-plan-form"].action = "/day-plans/save/";
  const guestOnly = new Set(["day-plan-signin"]);
  const listeners = {};
  const events = [];
  const document = {
    getElementById(id) {
      if (guest) return guestOnly.has(id) || id === "day-plan-panel" ? elements[id] : null;
      return guestOnly.has(id) ? null : elements[id];
    },
    createElement() { return element(); },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
    dispatchEvent(event) { events.push(event); },
  };
  class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } }
  const requests = [];
  vm.runInNewContext(source, {
    document, CustomEvent, URLSearchParams, Map, Math, Number, String, Object, Error,
    fetch(url, options) { requests.push({ url, options }); return fetch(url, options); },
  });
  const ui = {
    elements, events, requests,
    emit(name, detail) { for (const callback of listeners[name] || []) callback({ detail }); },
    select(pickup, dropoff) { ui.emit("taxiscope:zones-selected", { pickup, dropoff }); },
    add() { elements["day-plan-add"].listeners.click(); },
    // Select a trip and add it, then follow the builder's select-route like filters.js does.
    addTrip(pickup, dropoff) {
      ui.select(pickup, dropoff);
      ui.add();
      const last = events.filter(e => e.type === "taxiscope:select-route").at(-1);
      ui.select(last.detail.pickup, last.detail.dropoff);
    },
    stops() {
      return elements["day-plan-stops"].children.map(item => {
        const [label, maybeTime] = item.children;
        return [label.textContent, maybeTime.type === "time" ? maybeTime.value : null];
      });
    },
    timeInput(i) { return elements["day-plan-stops"].children[i].children[1]; },
    removeButton(i) { return elements["day-plan-stops"].children[i].children.at(-1); },
    saveDisabled() { return elements["day-plan-save"].disabled; },
    setName(value) {
      elements["day-plan-name"].value = value;
      elements["day-plan-name"].listeners.input();
    },
    submit() { return elements["day-plan-form"].listeners.submit({ preventDefault() {} }); },
    status() { return elements["day-plan-status"].textContent; },
  };
  ui.emit("taxiscope:map-ready", {
    data: {
      day: 0, hour: 8,
      features: Object.entries(NAMES).map(([id, name]) => ({ properties: { zone_id: Number(id), name } })),
    },
  });
  return ui;
}

test("first add takes the pickup and the dropoff", () => {
  const ui = setup();
  ui.select(33, 161);
  assert.equal(ui.elements["day-plan-panel"].hidden, false);
  assert.equal(ui.elements["day-plan-add"].hidden, false);
  ui.add();
  assert.deepEqual(ui.stops(), [["Brooklyn Heights", "08:00"], ["Midtown Center", null]]);
});

test("after adding, the last stop becomes the pickup and the dropoff is cleared", () => {
  const ui = setup();
  ui.select(33, 161);
  ui.add();
  const event = ui.events.find(e => e.type === "taxiscope:select-route");
  assert.deepEqual({ ...event.detail }, { pickup: 161, dropoff: null });
});

test("next add appends only the dropoff, with the next default time", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  assert.deepEqual(ui.stops(), [
    ["Brooklyn Heights", "08:00"], ["Midtown Center", "09:00"], ["Times Sq", null],
  ]);
});

test("a pickup changed by hand is added before the dropoff", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.addTrip(230, 12);
  assert.deepEqual(ui.stops().map(([name]) => name),
    ["Brooklyn Heights", "Midtown Center", "Times Sq", "Battery Park"]);
});

test("default leave times follow the map hour and stop at 23:45", () => {
  const ui = setup();
  ui.emit("taxiscope:time-changed", { day: 0, hour: 22 });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.addTrip(230, 12);
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["22:00", "23:00", "23:45", null]);
});

test("remove merges legs: the stop before keeps its time", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.addTrip(230, 12);
  ui.removeButton(1).listeners.click();
  assert.deepEqual(ui.stops(), [
    ["Brooklyn Heights", "08:00"], ["Times Sq", "10:00"], ["Battery Park", null],
  ]);
});

test("removing the last stop clears the new last time", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.removeButton(2).listeners.click();
  assert.deepEqual(ui.stops(), [["Brooklyn Heights", "08:00"], ["Midtown Center", null]]);
});

test("edited leave times are kept and sent", async () => {
  const ui = setup({ fetch: () => response(201, { id: 4, name: "Museum day", url: "/day-plans/4/" }) });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  const time = ui.timeInput(1);
  time.value = "11:15";
  time.listeners.input();
  ui.setName("Museum day");
  await ui.submit();
  const body = ui.requests[0].options.body;
  assert.equal(body.get("leave_times"), "08:00,11:15");
});

test("at most 10 stops", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  for (let i = 0; i < 8; i++) ui.addTrip(i % 2 ? 33 : 161, i % 2 ? 161 : 33);
  assert.equal(ui.stops().length, 10);
  ui.addTrip(33, 230);
  assert.equal(ui.stops().length, 10);
  assert.equal(ui.status(), "A day plan can have at most 10 stops.");
  assert.ok(ui.elements["day-plan-status"].classes.has("error"));
});

test("save is disabled until 3 stops, every time and a name", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.setName("Museum day");
  assert.equal(ui.saveDisabled(), true); // 2 stops
  ui.addTrip(161, 230);
  assert.equal(ui.saveDisabled(), false);
  const time = ui.timeInput(1);
  time.value = "11:20"; // not a quarter hour
  time.listeners.input();
  assert.equal(ui.saveDisabled(), true);
  time.value = "11:15";
  time.listeners.input();
  ui.setName("  ");
  assert.equal(ui.saveDisabled(), true);
});

test("save posts name, day, stops and leave_times with the CSRF header", async () => {
  const ui = setup({ fetch: () => response(201, { id: 4, name: "Museum day", url: "/day-plans/4/" }) });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.elements["day-plan-day"].value = "5";
  ui.setName(" Museum day ");
  await ui.submit();
  const { url, options } = ui.requests[0];
  assert.equal(url, "/day-plans/save/");
  assert.equal(options.method, "POST");
  assert.equal(options.headers["X-CSRFToken"], "csrf-test-token");
  assert.deepEqual(Object.fromEntries(options.body), {
    name: "Museum day", day_of_week: "5", stops: "33,161,230", leave_times: "08:00,09:00",
  });
});

test("201 shows a link to the plan and clears the builder", async () => {
  const ui = setup({ fetch: () => response(201, { id: 4, name: "Museum day", url: "/day-plans/4/" }) });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.setName("Museum day");
  await ui.submit();
  await settle();
  assert.equal(ui.status(), "Saved “Museum day” to My day plans.");
  assert.equal(ui.elements["day-plan-open"].hidden, false);
  assert.equal(ui.elements["day-plan-open"].href, "/day-plans/4/");
  assert.deepEqual(ui.stops(), []);
  assert.equal(ui.elements["day-plan-name"].value, "");
  assert.equal(ui.elements["day-plan-panel"].hidden, false); // the link stays visible
});

test("400 shows the errors and keeps the stops", async () => {
  const ui = setup({
    fetch: () => response(400, { errors: { name: ["You already have a day plan with this name."] } }),
  });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.setName("Museum day");
  await ui.submit();
  assert.equal(ui.status(), "You already have a day plan with this name.");
  assert.ok(ui.elements["day-plan-status"].classes.has("error"));
  assert.equal(ui.stops().length, 3);
});

test("401 asks to sign in", async () => {
  const ui = setup({ fetch: () => response(401, { message: "Sign in to save day plans" }) });
  ui.addTrip(33, 161);
  ui.addTrip(161, 230);
  ui.setName("Museum day");
  await ui.submit();
  assert.equal(ui.status(), "Sign in to save day plans.");
});

test("clear empties the builder", () => {
  const ui = setup();
  ui.addTrip(33, 161);
  ui.elements["day-plan-clear"].listeners.click();
  assert.deepEqual(ui.stops(), []);
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
});

test("guest page has no builder, only the sign-in link with both zones", () => {
  const ui = setup({ guest: true });
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
  ui.select(33, 161);
  assert.equal(ui.elements["day-plan-panel"].hidden, false);
  assert.equal(ui.elements["day-plan-signin"].hidden, false);
  ui.select(33, null);
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
});
