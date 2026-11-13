// US32 #94: the trip summary's "Find a shared ride" link carries the route and day.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../rides/static/rides/js/find-ride-link.js"), "utf8");

function setup({ guest = false, withLink = true } = {}) {
  const attributes = { href: "/rides/" };
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
      getElementById(id) { return withLink && id === "find-ride-link" ? link : null; },
      addEventListener(name, fn) { listeners[name] = fn; },
    },
  });
  return {
    link,
    href() { return attributes.href; },
    select(pickup, dropoff) { listeners["taxiscope:zones-selected"]({ detail: { pickup, dropoff } }); },
    time(day, hour = 9) { listeners["taxiscope:time-changed"]({ detail: { day, hour } }); },
    listeners,
  };
}

test("the link shows only for two different zones", () => {
  const ui = setup();
  assert.equal(ui.link.hidden, true);
  ui.select(161, null);
  assert.equal(ui.link.hidden, true);
  ui.select(161, 161);
  assert.equal(ui.link.hidden, true);
  ui.select(161, 132);
  assert.equal(ui.link.hidden, false);
  ui.select(null, null);
  assert.equal(ui.link.hidden, true);
});

test("the link carries the route and the selected day", () => {
  const ui = setup();
  ui.select(161, 132);
  assert.equal(ui.href(), "/rides/?from=161&to=132");
  ui.time(3);
  assert.equal(ui.href(), "/rides/?from=161&to=132&day=3");
  ui.time(0);
  assert.equal(ui.href(), "/rides/?from=161&to=132&day=0");
});

test("a day chosen before the zones is kept", () => {
  const ui = setup();
  ui.time(5);
  assert.equal(ui.link.hidden, true);
  ui.select(161, 132);
  assert.equal(ui.href(), "/rides/?from=161&to=132&day=5");
});

test("missing event fields count as no selection", () => {
  const ui = setup();
  ui.listeners["taxiscope:zones-selected"]({ detail: {} });
  assert.equal(ui.link.hidden, true);
  ui.select(161, 132);
  ui.listeners["taxiscope:time-changed"]({ detail: {} });
  assert.equal(ui.href(), "/rides/?from=161&to=132");
});

test("guests are sent to sign in, then back to the same search", () => {
  const ui = setup({ guest: true });
  ui.select(161, 132);
  ui.time(3);
  assert.equal(
    ui.href(),
    "/accounts/signin/?next=%2Frides%2F%3Ffrom%3D161%26to%3D132%26day%3D3"
  );
});

test("no link on the page means nothing to do", () => {
  const ui = setup({ withLink: false });
  assert.deepEqual(ui.listeners, {});
});
