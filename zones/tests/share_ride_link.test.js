// US31 #93: the trip summary's "Post a shared ride" link carries the selected route.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../rides/static/rides/js/share-ride-link.js"), "utf8");

function setup({ guest = false, withLink = true } = {}) {
  const attributes = { href: "/rides/new/" };
  const link = {
    hidden: true,
    dataset: guest ? { signin: "/accounts/signin/" } : {},
    getAttribute(name) { return attributes[name]; },
    setAttribute(name, value) { attributes[name] = value; },
  };
  const listeners = {};
  vm.runInNewContext(source, {
    URLSearchParams,
    document: {
      getElementById(id) { return withLink && id === "share-ride-link" ? link : null; },
      addEventListener(name, fn) { listeners[name] = fn; },
    },
  });
  return {
    link,
    href() { return attributes.href; },
    select(pickup, dropoff) { listeners["taxiscope:zones-selected"]({ detail: { pickup, dropoff } }); },
    listeners,
  };
}

test("the link shows only for two different zones", () => {
  const ui = setup();
  assert.equal(ui.link.hidden, true);
  ui.select(161, null);
  assert.equal(ui.link.hidden, true);
  ui.select(161, 237);
  assert.equal(ui.link.hidden, false);
  // A shared ride needs a different dropoff, so a trip within one zone has no link.
  ui.select(161, 161);
  assert.equal(ui.link.hidden, true);
  ui.select(null, null);
  assert.equal(ui.link.hidden, true);
});

test("the link opens the form with the route filled in", () => {
  const ui = setup();
  ui.select(161, 237);
  assert.equal(ui.href(), "/rides/new/?from=161&to=237");
  ui.select(4, 79);
  assert.equal(ui.href(), "/rides/new/?from=4&to=79");
});

test("guests go to sign in and come back to the same form", () => {
  const ui = setup({ guest: true });
  ui.select(161, 237);
  assert.equal(ui.href(), "/accounts/signin/?next=%2Frides%2Fnew%2F%3Ffrom%3D161%26to%3D237");
  ui.select(4, 79);
  assert.equal(ui.href(), "/accounts/signin/?next=%2Frides%2Fnew%2F%3Ffrom%3D4%26to%3D79");
});

test("a missing dropoff in the event counts as none", () => {
  const ui = setup();
  ui.select(161, 237);
  ui.listeners["taxiscope:zones-selected"]({ detail: { pickup: 161 } });
  assert.equal(ui.link.hidden, true);
});

test("pages without the link do nothing", () => {
  const ui = setup({ withLink: false });
  assert.deepEqual(Object.keys(ui.listeners), []);
});
