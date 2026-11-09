// US23 #70: "Save this comparison" at the bottom of the compare card.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../routes/static/routes/js/save-comparison.js"), "utf8");

function setup(fetch, guest = false) {
  const elements = {};
  for (const id of ["save-comparison-panel", "save-comparison-form", "save-comparison-status",
    "save-comparison-signin", "save-comparison-button", "comparison-name"]) {
    const attributes = { href: "/accounts/signin/" };
    elements[id] = {
      hidden: id === "save-comparison-panel" || (id === "save-comparison-signin" && !guest),
      value: "", textContent: "", disabled: false, listeners: {}, classes: new Set(),
      classList: {
        add(name) { elements[id].classes.add(name); },
        remove(name) { elements[id].classes.delete(name); },
      },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      querySelector() { return { value: "csrf-test-token" }; },
      getAttribute(name) { return attributes[name]; },
      setAttribute(name, value) { attributes[name] = value; },
      action: "/comparisons/save/",
    };
  }
  const listeners = {};
  vm.runInNewContext(source, {
    document: {
      getElementById(id) { return guest && id === "save-comparison-form" ? null : elements[id]; },
      addEventListener(name, callback) { listeners[name] = callback; },
    },
    fetch, URLSearchParams, encodeURIComponent,
  });
  return {
    elements,
    change(a, b, address = "/compare/") {
      listeners["taxiscope:compare-changed"]({ detail: { a, b, address } });
    },
    submit() { return elements["save-comparison-form"].listeners.submit({ preventDefault() {} }); },
  };
}
const response = (status, data) => ({ status, ok: status < 400, json: async () => data });

test("the save row shows only once both zones are picked", () => {
  for (const guest of [false, true]) {
    const ui = setup(() => assert.fail("no request expected"), guest);
    assert.equal(ui.elements["save-comparison-panel"].hidden, true);
    ui.change(1, null);
    assert.equal(ui.elements["save-comparison-panel"].hidden, true);
    ui.change(null, 2);
    assert.equal(ui.elements["save-comparison-panel"].hidden, true);
    ui.change(1, 2);
    assert.equal(ui.elements["save-comparison-panel"].hidden, false);
    ui.change(null, null);
    assert.equal(ui.elements["save-comparison-panel"].hidden, true);
  }
});

test("guests get a sign-in link that comes back to this comparison", () => {
  const ui = setup(() => assert.fail("no request expected"), true);
  ui.change(161, 132, "/compare/?a=161&b=132&day=1&hour=17");
  assert.equal(ui.elements["save-comparison-signin"].hidden, false);
  assert.equal(
    ui.elements["save-comparison-signin"].getAttribute("href"),
    "/accounts/signin/?next=%2Fcompare%2F%3Fa%3D161%26b%3D132%26day%3D1%26hour%3D17"
  );
});

test("sends the name, A and B in the order picked, with the CSRF token", async () => {
  let request;
  const ui = setup(async (url, options) => {
    request = { url, options };
    return response(201, { id: 9, name: "<b>Work vs airport</b>" });
  });
  ui.change(161, 132);
  ui.elements["comparison-name"].value = "Work vs airport";
  await ui.submit();
  assert.equal(request.url, "/comparisons/save/");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["X-CSRFToken"], "csrf-test-token");
  assert.equal(request.options.body.toString(), "name=Work+vs+airport&zone_a=161&zone_b=132");
  // Shown as text, never as HTML.
  assert.equal(ui.elements["save-comparison-status"].textContent, "Saved “<b>Work vs airport</b>”.");
  assert.equal(ui.elements["comparison-name"].value, "");
  assert.equal(ui.elements["save-comparison-button"].disabled, false);
});

test("shows the field errors from a 400", async () => {
  const ui = setup(async () => response(400, {
    errors: { name: ["You already have a saved comparison with this name."] },
  }));
  ui.change(161, 132);
  ui.elements["comparison-name"].value = "Taken";
  await ui.submit();
  assert.equal(ui.elements["save-comparison-status"].textContent,
    "You already have a saved comparison with this name.");
  assert.ok(ui.elements["save-comparison-status"].classes.has("error"));
  assert.equal(ui.elements["comparison-name"].value, "Taken");
});

test("a 401 (signed out meanwhile) swaps the form for the sign-in link", async () => {
  const ui = setup(async () => response(401, { message: "Sign in to save comparisons" }));
  ui.change(161, 132);
  await ui.submit();
  assert.equal(ui.elements["save-comparison-form"].hidden, true);
  assert.equal(ui.elements["save-comparison-signin"].hidden, false);
});

test("a 403 asks to reload, and a network failure says so", async () => {
  let ui = setup(async () => response(403, {}));
  ui.change(161, 132);
  await ui.submit();
  assert.match(ui.elements["save-comparison-status"].textContent, /Reload the page/);
  ui = setup(async () => { throw new TypeError("Failed to fetch"); });
  ui.change(161, 132);
  await ui.submit();
  assert.equal(ui.elements["save-comparison-status"].textContent,
    "Could not save this comparison. Check your connection and try again.");
});

test("a reply for zones that have since changed is ignored", async () => {
  let finish;
  const ui = setup(() => new Promise(resolve => { finish = resolve; }));
  ui.change(161, 132);
  ui.elements["comparison-name"].value = "Old pair";
  const pending = ui.submit();
  ui.change(161, 7);
  finish(response(201, { id: 1, name: "Old pair" }));
  await pending;
  assert.equal(ui.elements["save-comparison-status"].textContent, "");
});
