const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../routes/static/routes/js/save-route.js"), "utf8");
function setup(fetch, guest = false) {
  const elements = {};
  for (const id of ["save-route-panel", "save-route-form", "save-route-status",
    "save-route-signin", "save-route-button", "route-name"]) {
    elements[id] = {
      hidden: id === "save-route-panel" || (id === "save-route-signin" && !guest),
      value: "", textContent: "", disabled: false, listeners: {},
      classList: { add() {}, remove() {} },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      querySelector() { return { value: "csrf-test-token" }; },
      action: "/saved-routes/save/",
    };
  }
  const listeners = {};
  vm.runInNewContext(source, {
    document: {
      getElementById(id) { return guest && id === "save-route-form" ? null : elements[id]; },
      addEventListener(name, callback) { listeners[name] = callback; },
    },
    fetch, URLSearchParams,
  });
  return {
    elements,
    select(pickup, dropoff) {
      listeners["taxiscope:zones-selected"]({ detail: { pickup, dropoff } });
    },
    submit() { return elements["save-route-form"].listeners.submit({ preventDefault() {} }); },
  };
}
const response = (status, data) => ({ status, ok: status < 400, json: async () => data });

test("save controls require both zones; guests get the prompt without a form", () => {
  for (const guest of [false, true]) {
    const ui = setup(() => assert.fail("no request expected"), guest);
    assert.equal(ui.elements["save-route-panel"].hidden, true);
    ui.select(1, null);
    assert.equal(ui.elements["save-route-panel"].hidden, true);
    ui.select(1, 2);
    assert.equal(ui.elements["save-route-panel"].hidden, false);
    ui.select(1, 1);
    assert.equal(ui.elements["save-route-panel"].hidden, false);
    ui.select(null, null);
    assert.equal(ui.elements["save-route-panel"].hidden, true);
  }
});

test("sends selected pair and CSRF token, then displays saved name as text", async () => {
  let request;
  const ui = setup(async (url, options) => {
    request = { url, options };
    return response(201, { name: "<b>Home</b>" });
  });
  ui.select(1, 2);
  ui.elements["route-name"].value = "<b>Home</b>";
  await ui.submit();
  assert.equal(request.url, "/saved-routes/save/");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["X-CSRFToken"], "csrf-test-token");
  assert.equal(request.options.body.get("pickup_zone"), "1");
  assert.equal(request.options.body.get("dropoff_zone"), "2");
  assert.equal(request.options.body.get("name"), "<b>Home</b>");
  assert.equal(ui.elements["save-route-status"].textContent, "Saved “<b>Home</b>”.");
  assert.equal(ui.elements["route-name"].value, "");
  assert.equal(ui.elements["save-route-button"].disabled, false);
});

test("validation failures retain the name for correction", async () => {
  const ui = setup(async () => response(400, { errors: { name: ["Already saved."] } }));
  ui.select(1, 2);
  ui.elements["route-name"].value = "Home";
  await ui.submit();
  assert.equal(ui.elements["save-route-status"].textContent, "Already saved.");
  assert.equal(ui.elements["route-name"].value, "Home");
  assert.equal(ui.elements["save-route-button"].disabled, false);
});

test("blocks double submits and ignores stale responses after changing zones", async () => {
  let resolve;
  let count = 0;
  const ui = setup(() => {
    count++;
    return new Promise(done => { resolve = done; });
  });
  ui.select(1, 2);
  ui.elements["route-name"].value = "Old route";
  const pending = ui.submit();
  assert.equal(ui.elements["save-route-button"].disabled, true);
  await ui.submit();
  assert.equal(count, 1);
  ui.select(3, 4);
  ui.elements["route-name"].value = "New route";
  resolve(response(201, { name: "Old route" }));
  await pending;
  assert.equal(ui.elements["save-route-status"].textContent, "");
  assert.equal(ui.elements["route-name"].value, "New route");
  assert.equal(ui.elements["save-route-button"].disabled, false);
});

test("expired login replaces the form with a sign-in prompt", async () => {
  const ui = setup(async () => response(401, {}));
  ui.select(1, 2);
  await ui.submit();
  assert.equal(ui.elements["save-route-form"].hidden, true);
  assert.equal(ui.elements["save-route-signin"].hidden, false);
  assert.equal(ui.elements["save-route-status"].textContent, "");
});

test("CSRF expiry and offline requests show actionable messages and permit retry", async () => {
  for (const [fetch, message] of [
    [async () => response(403, {}), /Reload the page/],
    [async () => { throw new Error("Failed to fetch"); }, /Check your connection/],
  ]) {
    const ui = setup(fetch);
    ui.select(1, 2);
    await ui.submit();
    assert.match(ui.elements["save-route-status"].textContent, message);
    assert.equal(ui.elements["save-route-button"].disabled, false);
  }
});
