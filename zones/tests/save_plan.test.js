// US17 #46: "Save this plan" under the Leave by results.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../routes/static/routes/js/save-plan.js"), "utf8");

function setup(fetch, guest = false) {
  const elements = {};
  for (const id of ["save-plan-panel", "save-plan-form", "save-plan-status", "save-plan-button", "plan-name"]) {
    elements[id] = {
      hidden: id === "save-plan-panel", value: "", textContent: "", disabled: false, listeners: {},
      classList: { add() {}, remove() {} },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      querySelector() { return { value: "csrf-test-token" }; },
      action: "/plans/save/",
    };
  }
  const listeners = {};
  vm.runInNewContext(source, {
    document: {
      getElementById(id) { return guest && id === "save-plan-form" ? null : elements[id]; },
      addEventListener(name, callback) { listeners[name] = callback; },
    },
    fetch, URLSearchParams, Object, Error,
  });
  const emit = (name, detail) => listeners[name]({ detail });
  return {
    elements, emit,
    submit() { return elements["save-plan-form"].listeners.submit({ preventDefault() {} }); },
  };
}
const response = (status, data) => ({ status, ok: status < 400, json: async () => data });

test("appears only after a result for a selected trip and hides when it is cleared", () => {
  const ui = setup(() => assert.fail("no request expected"));
  ui.emit("taxiscope:plan-result", { mode: "cheapest", day: 4, time: "22:00" });
  assert.equal(ui.elements["save-plan-panel"].hidden, true); // no zones yet
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.emit("taxiscope:plan-result", { mode: "cheapest", day: 4, time: "22:00" });
  assert.equal(ui.elements["save-plan-panel"].hidden, false);
  ui.emit("taxiscope:plan-cleared", { mode: "cheapest" });
  assert.equal(ui.elements["save-plan-panel"].hidden, true);
});

test("saves the plan behind the shown result, including a Now time", async () => {
  const calls = [];
  const ui = setup(async (url, options) => {
    calls.push({ url, options });
    return response(201, { id: 7, name: "Late commute" });
  });
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.emit("taxiscope:plan-result", { mode: "cheapest", day: 4, time: "22:37" });
  ui.elements["plan-name"].value = "Late commute";
  await ui.submit();
  assert.equal(calls[0].url, "/plans/save/");
  assert.equal(calls[0].options.headers["X-CSRFToken"], "csrf-test-token");
  assert.equal(
    calls[0].options.body.toString(),
    "name=Late+commute&pickup_zone=1&dropoff_zone=2&mode=cheapest&day_of_week=4&time=22%3A37"
  );
  assert.match(ui.elements["save-plan-status"].textContent, /Saved “Late commute” to My plans/);
  assert.equal(ui.elements["plan-name"].value, "");
});

test("shows the server's validation message", async () => {
  const ui = setup(async () => response(400, { errors: { name: ["You already have a saved plan with this name."] } }));
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.emit("taxiscope:plan-result", { mode: "arrive_by", day: 0, time: "09:15" });
  ui.elements["plan-name"].value = "Commute";
  await ui.submit();
  assert.equal(ui.elements["save-plan-status"].textContent, "You already have a saved plan with this name.");
});

test("guests get no form, and nothing breaks", () => {
  const ui = setup(() => assert.fail("no request expected"), true);
  ui.emit("taxiscope:zones-selected", { pickup: 1, dropoff: 2 });
  ui.emit("taxiscope:plan-result", { mode: "arrive_by", day: 0, time: "09:15" });
  assert.equal(ui.elements["save-plan-panel"].hidden, false);
});
