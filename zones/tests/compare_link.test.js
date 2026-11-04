// US22 #69 (added beyond the acceptance criteria): the map's "Compare" link
// carries the map's day, hour and selected pickup (as A).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/zones/js/compare-link.js"), "utf8");

function setup({ withLink = true } = {}) {
  const attributes = { href: "/compare/" };
  const link = {
    getAttribute(name) { return attributes[name]; },
    setAttribute(name, value) { attributes[name] = value; },
  };
  const listeners = {};
  vm.runInNewContext(source, {
    URLSearchParams,
    document: {
      getElementById(id) { return withLink && id === "compare-link" ? link : null; },
      addEventListener(name, fn) { listeners[name] = fn; },
    },
  });
  return {
    href() { return attributes.href; },
    send(name, detail) { listeners[name]({ detail }); },
    listeners,
  };
}

test("the link starts as plain /compare/ and gets the map's day and hour", () => {
  const ui = setup();
  assert.equal(ui.href(), "/compare/");
  ui.send("taxiscope:map-ready", { data: { day: 1, hour: 17 } });
  assert.equal(ui.href(), "/compare/?day=1&hour=17");
});

test("the link follows time changes", () => {
  const ui = setup();
  ui.send("taxiscope:map-ready", { data: { day: 1, hour: 17 } });
  ui.send("taxiscope:time-changed", { day: 5, hour: 0 });
  assert.equal(ui.href(), "/compare/?day=5&hour=0");
});

test("the selected pickup becomes A; the dropoff is not carried", () => {
  const ui = setup();
  ui.send("taxiscope:map-ready", { data: { day: 1, hour: 17 } });
  ui.send("taxiscope:zones-selected", { pickup: 161, dropoff: 132 });
  assert.equal(ui.href(), "/compare/?a=161&day=1&hour=17");
  ui.send("taxiscope:zones-selected", { pickup: null, dropoff: null });
  assert.equal(ui.href(), "/compare/?day=1&hour=17");
});

test("does nothing on a page without the link", () => {
  const ui = setup({ withLink: false });
  assert.deepEqual(Object.keys(ui.listeners), []);
});
