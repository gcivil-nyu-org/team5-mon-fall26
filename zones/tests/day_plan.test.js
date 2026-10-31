// US20 #49: build a multi-stop day plan on the map with "+ Add stop".
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
const NAMES = { 33: "Brooklyn Heights", 161: "Midtown Center", 230: "Times Sq", 12: "Battery Park", 43: "Central Park" };
const BH = 33, MC = 161, TS = 230, BP = 12, CP = 43;

// A fake page: day-plan.js plus the parts of filters.js it talks to.
function setup({ fetch = () => assert.fail("no request expected"), guest = false } = {}) {
  const elements = Object.fromEntries(IDS.map(id => [id, element()]));
  elements["day-plan-panel"].hidden = true;
  elements["day-plan-open"].hidden = true;
  elements["day-plan-form"].action = "/day-plans/save/";
  const listeners = {};
  const events = [];
  const map = { day: 0, hour: 8, pickup: null, dropoff: null, picking: false };
  const emit = (name, detail) => { for (const callback of listeners[name] || []) callback({ detail }); };
  const select = (pickup, dropoff) => {
    Object.assign(map, { pickup, dropoff });
    emit("taxiscope:zones-selected", { pickup, dropoff });
  };
  const document = {
    getElementById(id) {
      if (guest) return ["day-plan-signin", "day-plan-panel"].includes(id) ? elements[id] : null;
      return id === "day-plan-signin" ? null : elements[id];
    },
    createElement() { return element(); },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
    dispatchEvent(event) {
      events.push(event);
      const { type, detail } = event;
      if (type === "taxiscope:stop-picking") map.picking = detail.active;
      if (type === "taxiscope:select-route") select(detail.pickup, detail.dropoff); // like selectRoute
      if (type === "taxiscope:set-time") {
        // Like filters.js: move the filters, reload, then send time-changed.
        const day = detail.day ?? map.day;
        const hour = detail.hour ?? map.hour;
        if (day === map.day && hour === map.hour) return;
        Object.assign(map, { day, hour });
        setImmediate(() => emit("taxiscope:time-changed", { day, hour }));
      }
    },
  };
  class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } }
  const requests = [];
  vm.runInNewContext(source, {
    document, CustomEvent, URLSearchParams, Map, Math, Number, String, Object, Error,
    fetch(url, options) { requests.push({ url, options }); return fetch(url, options); },
  });
  const ui = {
    elements, events, requests, map, select,
    // A map click: picks a stop while armed, otherwise selects as usual.
    click(zone) {
      if (map.picking) emit("taxiscope:stop-picked", { zone });
      else if (map.pickup === null) select(zone, null);
      else select(map.pickup, zone);
    },
    press() { elements["day-plan-add"].listeners.click(); },
    pressed() { return elements["day-plan-add"].attributes["aria-pressed"] === "true"; },
    // Header filters moved by the rider (filters.js then sends time-changed).
    moveSlider(hour) { map.hour = hour; emit("taxiscope:time-changed", { day: map.day, hour }); },
    changeHeaderDay(day) { map.day = day; emit("taxiscope:time-changed", { day, hour: map.hour }); },
    stops() {
      return elements["day-plan-stops"].children.map(item => {
        const [label, maybeTime] = item.children;
        return [label.textContent, maybeTime.type === "time" ? maybeTime.value : null];
      });
    },
    editTime(i, value) {
      const input = elements["day-plan-stops"].children[i].children[1];
      input.value = value;
      input.listeners.input();
    },
    remove(i) { elements["day-plan-stops"].children[i].children.at(-1).listeners.click(); },
    sent(type) { return events.filter(e => e.type === type).map(e => ({ ...e.detail })); },
    setName(value) {
      elements["day-plan-name"].value = value;
      elements["day-plan-name"].listeners.input();
    },
    submit() { return elements["day-plan-form"].listeners.submit({ preventDefault() {} }); },
    status() { return elements["day-plan-status"].textContent; },
    saveDisabled() { return elements["day-plan-save"].disabled; },
  };
  emit("taxiscope:map-ready", {
    data: {
      day: 0, hour: 8,
      features: Object.entries(NAMES).map(([id, name]) => ({ properties: { zone_id: Number(id), name } })),
    },
  });
  return ui;
}

// Brooklyn Heights → Midtown Center → Times Sq, built with two presses.
function threeStops(ui) {
  ui.select(BH, MC);
  ui.press();
  ui.click(TS);
}

test("+ Add stop shows only with a pickup and a dropoff, with no message", () => {
  const ui = setup();
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
  ui.select(BH, null);
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
  ui.select(BH, MC);
  assert.equal(ui.elements["day-plan-panel"].hidden, false);
  assert.equal(ui.elements["day-plan-add"].hidden, false);
  assert.equal(ui.status(), "");
});

test("first press records the pickup and dropoff as stops 1 and 2 and arms", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  assert.deepEqual(ui.stops(), [["Brooklyn Heights", "08:00"], ["Midtown Center", null]]);
  assert.equal(ui.pressed(), true);
  assert.deepEqual(ui.sent("taxiscope:stop-picking"), [{ active: true }]);
  assert.equal(ui.status(), "");
});

test("an armed press adds exactly one stop, then the button is back to normal", () => {
  const ui = setup();
  threeStops(ui);
  assert.deepEqual(ui.stops().map(([name]) => name), ["Brooklyn Heights", "Midtown Center", "Times Sq"]);
  assert.equal(ui.pressed(), false);
  assert.deepEqual(ui.sent("taxiscope:stop-picking").at(-1), { active: false });
  ui.click(BP); // not armed any more
  assert.equal(ui.stops().length, 3);
});

test("map clicks without pressing add nothing and select as usual", () => {
  const ui = setup();
  ui.click(BH);
  ui.click(MC);
  assert.deepEqual(ui.stops(), []);
  assert.deepEqual([ui.map.pickup, ui.map.dropoff], [BH, MC]);
  assert.deepEqual(ui.sent("taxiscope:stop-picked"), []);
});

test("pressing again while armed cancels", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  ui.press();
  assert.equal(ui.pressed(), false);
  assert.deepEqual(ui.sent("taxiscope:stop-picking").at(-1), { active: false });
  ui.click(TS);
  assert.equal(ui.stops().length, 2);
  assert.deepEqual([ui.map.pickup, ui.map.dropoff], [BH, TS]); // an ordinary click
});

test("clicking the current last stop while armed does nothing and stays armed", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  ui.click(MC);
  assert.equal(ui.stops().length, 2);
  assert.equal(ui.pressed(), true);
  ui.click(TS);
  assert.equal(ui.stops().length, 3);
});

test("after a stop is added, the newest leg becomes the selection", () => {
  const ui = setup();
  threeStops(ui);
  assert.deepEqual(ui.sent("taxiscope:select-route").at(-1), { pickup: MC, dropoff: TS });
  assert.deepEqual([ui.map.pickup, ui.map.dropoff], [MC, TS]);
  assert.equal(ui.elements["day-plan-add"].hidden, false); // ready for the next stop
});

test("adding a stop moves the header hour to the new leg's leave hour", async () => {
  const ui = setup();
  threeStops(ui);
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["08:00", "09:00", null]);
  assert.deepEqual(ui.sent("taxiscope:set-time"), [{ hour: 9 }]);
  await settle(); // filters.js echoes time-changed; the leave times stay as they are
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["08:00", "09:00", null]);
});

test("new legs default to an hour after the previous one, at most 23:45", async () => {
  const ui = setup();
  ui.moveSlider(22);
  ui.select(BH, MC);
  ui.press();
  ui.click(TS);
  await settle();
  ui.press();
  ui.click(BP);
  await settle();
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["22:00", "23:00", "23:45", null]);
});

test("header day changes move the builder's day, and the other way round", async () => {
  const ui = setup();
  threeStops(ui);
  ui.changeHeaderDay(4);
  assert.equal(ui.elements["day-plan-day"].value, "4");
  ui.elements["day-plan-day"].value = "6";
  ui.elements["day-plan-day"].listeners.change();
  assert.deepEqual(ui.sent("taxiscope:set-time").at(-1), { day: 6 });
  await settle();
  assert.equal(ui.map.day, 6);
  assert.equal(ui.elements["day-plan-day"].value, "6");
});

test("a day change keeps a custom leave time", async () => {
  const ui = setup();
  threeStops(ui);
  await settle();
  ui.editTime(1, "09:45");
  ui.changeHeaderDay(2);
  assert.equal(ui.stops()[1][1], "09:45");
});

test("moving the hour slider sets only the newest leg's leave time to HH:00", () => {
  const ui = setup();
  threeStops(ui);
  ui.moveSlider(14);
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["08:00", "14:00", null]);
});

test("editing the newest leg's time moves the slider; an earlier leg's does not", async () => {
  const ui = setup();
  threeStops(ui);
  await settle();
  ui.editTime(1, "11:15");
  assert.deepEqual(ui.sent("taxiscope:set-time").at(-1), { hour: 11 });
  await settle();
  assert.equal(ui.map.hour, 11);
  assert.equal(ui.stops()[1][1], "11:15"); // the echo keeps the minutes
  const before = ui.sent("taxiscope:set-time").length;
  ui.editTime(0, "07:30");
  assert.equal(ui.sent("taxiscope:set-time").length, before);
  assert.deepEqual(ui.stops().map(([, leave]) => leave), ["07:30", "11:15", null]);
});

test("removing the last stop selects the new newest leg, without adding the zone back", async () => {
  const ui = setup();
  threeStops(ui);
  ui.press();
  ui.click(BP);
  await settle();
  ui.remove(3);
  assert.deepEqual(ui.stops(), [
    ["Brooklyn Heights", "08:00"], ["Midtown Center", "09:00"], ["Times Sq", null],
  ]);
  assert.deepEqual(ui.sent("taxiscope:select-route").at(-1), { pickup: MC, dropoff: TS });
  assert.deepEqual(ui.sent("taxiscope:set-time").at(-1), { hour: 9 });
  await settle();
  assert.equal(ui.stops().length, 3);
});

test("removing a middle stop merges its legs; the stop before keeps its time", async () => {
  const ui = setup();
  threeStops(ui);
  ui.press();
  ui.click(BP);
  await settle();
  const selections = ui.sent("taxiscope:select-route").length;
  ui.remove(1);
  assert.deepEqual(ui.stops(), [
    ["Brooklyn Heights", "08:00"], ["Times Sq", "10:00"], ["Battery Park", null],
  ]);
  assert.equal(ui.sent("taxiscope:select-route").length, selections); // newest leg unchanged
});

test("removing down to one stop clears the builder", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  ui.remove(1);
  assert.deepEqual(ui.stops(), []);
  assert.equal(ui.pressed(), false);
  assert.deepEqual(ui.sent("taxiscope:select-route").at(-1), { pickup: BH, dropoff: null });
});

test("at most 10 stops: the button is disabled", async () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  const zones = [TS, BP, CP];
  for (let i = 0; i < 8; i++) {
    if (!ui.pressed()) ui.press(); // the first press already armed it
    ui.click(zones[i % 3]);
    await settle();
  }
  assert.equal(ui.stops().length, 10);
  assert.equal(ui.elements["day-plan-add"].disabled, true);
  ui.press();
  assert.equal(ui.pressed(), false);
});

test("save is disabled until 3 stops, every time and a name", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  ui.setName("Museum day");
  assert.equal(ui.saveDisabled(), true); // 2 stops
  ui.click(TS);
  assert.equal(ui.saveDisabled(), false);
  ui.editTime(0, "08:20"); // not a quarter hour
  assert.equal(ui.saveDisabled(), true);
  ui.editTime(0, "08:15");
  ui.setName("  ");
  assert.equal(ui.saveDisabled(), true);
});

test("save posts name, day, stops and leave_times with the CSRF header", async () => {
  const ui = setup({ fetch: () => response(201, { id: 4, name: "Museum day", url: "/day-plans/4/" }) });
  threeStops(ui);
  ui.changeHeaderDay(5);
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
  threeStops(ui);
  ui.setName("Museum day");
  await ui.submit();
  assert.equal(ui.status(), "Saved “Museum day” to My day plans.");
  assert.equal(ui.elements["day-plan-open"].hidden, false);
  assert.equal(ui.elements["day-plan-open"].href, "/day-plans/4/");
  assert.deepEqual(ui.stops(), []);
  assert.equal(ui.elements["day-plan-name"].value, "");
  assert.equal(ui.elements["day-plan-panel"].hidden, false);
});

test("400 shows the errors and keeps the stops", async () => {
  const ui = setup({
    fetch: () => response(400, { errors: { name: ["You already have a day plan with this name."] } }),
  });
  threeStops(ui);
  ui.setName("Museum day");
  await ui.submit();
  assert.equal(ui.status(), "You already have a day plan with this name.");
  assert.ok(ui.elements["day-plan-status"].classes.has("error"));
  assert.equal(ui.stops().length, 3);
});

test("401 asks to sign in", async () => {
  const ui = setup({ fetch: () => response(401, { message: "Sign in to save day plans" }) });
  threeStops(ui);
  ui.setName("Museum day");
  await ui.submit();
  assert.equal(ui.status(), "Sign in to save day plans.");
});

test("clear empties the builder and disarms", () => {
  const ui = setup();
  ui.select(BH, MC);
  ui.press();
  ui.elements["day-plan-clear"].listeners.click();
  assert.deepEqual(ui.stops(), []);
  assert.equal(ui.pressed(), false);
});

test("guests see only the sign-in link, with both zones selected", () => {
  const ui = setup({ guest: true });
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
  ui.select(BH, MC);
  assert.equal(ui.elements["day-plan-panel"].hidden, false);
  assert.equal(ui.elements["day-plan-signin"].hidden, false);
  ui.select(BH, null);
  assert.equal(ui.elements["day-plan-panel"].hidden, true);
});
