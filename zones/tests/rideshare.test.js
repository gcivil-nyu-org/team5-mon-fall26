// US28 #75: "Taxi vs. rideshare" in the trip summary.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../static/zones/js/rideshare.js"), "utf8"
);
const settle = () => new Promise(resolve => setImmediate(resolve));
const ok = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });

const IDS = [
  "rideshare-panel", "rideshare-status", "rideshare-verdict",
  "rideshare-taxi-fare", "rideshare-taxi-range", "rideshare-taxi-duration",
  "rideshare-ride-fare", "rideshare-ride-range", "rideshare-ride-duration", "rideshare-ride-wait",
];

const TAXI = {
  enough_data: true, trip_count: 120, fare_min: "8.00", fare_avg: "21.07",
  fare_max: "45.10", avg_duration_min: 14.25,
};
const RIDESHARE = {
  enough_data: true, trip_count: 85, fare_min: "9.10", fare_avg: "24.40",
  fare_max: "61.20", avg_duration_min: 12.5, avg_wait_min: 4.5,
};
const NOT_ENOUGH = {
  enough_data: false, trip_count: 3, fare_min: null, fare_avg: null,
  fare_max: null, avg_duration_min: null, avg_wait_min: null,
};

// answer(url) returns the response for each request, by endpoint.
function setup(answer) {
  const elements = Object.fromEntries(
    IDS.map(id => [id, { hidden: true, textContent: "", dataset: {} }])
  );
  const listeners = {};
  const requests = [];
  const fetch = url => {
    requests.push(url);
    return answer(url);
  };
  const document = {
    getElementById(id) { return elements[id]; },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
  };
  const console = { error() {} };
  vm.runInNewContext(source, {
    document, fetch, URLSearchParams, Number, Math, Promise, Error, Object, console,
  });
  const ui = {
    elements, requests,
    emit(name, detail) { for (const callback of listeners[name] || []) callback({ detail }); },
    select(pickup, dropoff) { ui.emit("taxiscope:zones-selected", { pickup, dropoff }); },
    text(id) { return elements[id].textContent; },
  };
  ui.emit("taxiscope:map-ready", { data: { day: 0, hour: 8 } });
  return ui;
}

function byEndpoint(taxi, rideshare) {
  return url => (url.startsWith("/api/routes/rideshare?") ? ok(rideshare) : ok(taxi));
}

test("hidden with no zones and with a pickup only", async () => {
  const ui = setup(byEndpoint(TAXI, RIDESHARE));
  assert.equal(ui.elements["rideshare-panel"].hidden, true);
  ui.select(161, null);
  await settle();
  assert.equal(ui.elements["rideshare-panel"].hidden, true);
  assert.deepEqual(ui.requests, []);
});

test("both zones show taxi and rideshare side by side", async () => {
  const ui = setup(byEndpoint(TAXI, RIDESHARE));
  ui.select(161, 237);
  await settle();
  assert.equal(ui.elements["rideshare-panel"].hidden, false);
  assert.deepEqual(ui.requests, [
    "/api/routes?from=161&to=237&day=0&hour=8",
    "/api/routes/rideshare?from=161&to=237&day=0&hour=8",
  ]);
  assert.equal(ui.text("rideshare-taxi-fare"), "$21.07");
  assert.equal(ui.text("rideshare-taxi-range"), "$8.00–$45.10");
  assert.equal(ui.text("rideshare-taxi-duration"), "14.3 min");
  assert.equal(ui.text("rideshare-ride-fare"), "$24.40");
  assert.equal(ui.text("rideshare-ride-range"), "$9.10–$61.20");
  assert.equal(ui.text("rideshare-ride-duration"), "12.5 min");
  assert.equal(ui.text("rideshare-ride-wait"), "4.5 min");
});

test("says the taxi was cheaper, and by how much", async () => {
  const ui = setup(byEndpoint(TAXI, RIDESHARE));
  ui.select(161, 237);
  await settle();
  const verdict = ui.elements["rideshare-verdict"];
  assert.equal(verdict.hidden, false);
  // 24.40 - 21.07 = 3.33, which is 14% of 24.40.
  assert.equal(verdict.textContent, "Taxi was cheaper at this time, by $3.33 on average (14% less).");
  assert.equal(verdict.dataset.cheaper, "taxi");
  assert.equal(ui.text("rideshare-status"), "");
});

test("says Uber/Lyft was cheaper when it was", async () => {
  const ui = setup(byEndpoint({ ...TAXI, fare_avg: "30.00" }, RIDESHARE));
  ui.select(161, 237);
  await settle();
  // 30.00 - 24.40 = 5.60, which is 19% of 30.00.
  assert.equal(
    ui.text("rideshare-verdict"),
    "Uber/Lyft was cheaper at this time, by $5.60 on average (19% less)."
  );
  assert.equal(ui.elements["rideshare-verdict"].dataset.cheaper, "rideshare");
});

test("equal average fares are called the same", async () => {
  const ui = setup(byEndpoint({ ...TAXI, fare_avg: "24.40" }, RIDESHARE));
  ui.select(161, 237);
  await settle();
  assert.equal(ui.text("rideshare-verdict"), "Taxi and Uber/Lyft had the same average fare at this time.");
});

test("each side shows Not enough data on its own, with no verdict", async () => {
  for (const [taxi, rideshare, lacking, fine] of [
    [NOT_ENOUGH, RIDESHARE, "taxi", "ride"],
    [TAXI, NOT_ENOUGH, "ride", "taxi"],
  ]) {
    const ui = setup(byEndpoint(taxi, rideshare));
    ui.select(161, 237);
    await settle();
    assert.equal(ui.text(`rideshare-${lacking}-fare`), "Not enough data");
    assert.equal(ui.text(`rideshare-${lacking}-range`), "Not enough data");
    assert.equal(ui.text(`rideshare-${lacking}-duration`), "Not enough data");
    assert.notEqual(ui.text(`rideshare-${fine}-fare`), "Not enough data");
    assert.equal(ui.elements["rideshare-verdict"].hidden, true);
    assert.equal(
      ui.text("rideshare-status"),
      "Both need at least 5 past trips at this time to say which was cheaper."
    );
  }
});

test("a null wait shows Not enough data for the wait only", async () => {
  const ui = setup(byEndpoint(TAXI, { ...RIDESHARE, avg_wait_min: null }));
  ui.select(161, 237);
  await settle();
  assert.equal(ui.text("rideshare-ride-wait"), "Not enough data");
  assert.equal(ui.text("rideshare-ride-fare"), "$24.40");
  assert.equal(ui.elements["rideshare-verdict"].hidden, false);
});

test("reloads when the zones, the day or the hour change", async () => {
  const ui = setup(byEndpoint(TAXI, RIDESHARE));
  ui.select(161, 237);
  await settle();
  ui.select(161, 132);
  await settle();
  ui.emit("taxiscope:time-changed", { day: 5, hour: 23 });
  await settle();
  assert.deepEqual(ui.requests.filter(url => url.startsWith("/api/routes/rideshare")), [
    "/api/routes/rideshare?from=161&to=237&day=0&hour=8",
    "/api/routes/rideshare?from=161&to=132&day=0&hour=8",
    "/api/routes/rideshare?from=161&to=132&day=5&hour=23",
  ]);
});

test("clearing the dropoff hides the section", async () => {
  const ui = setup(byEndpoint(TAXI, RIDESHARE));
  ui.select(161, 237);
  await settle();
  ui.select(161, null);
  assert.equal(ui.elements["rideshare-panel"].hidden, true);
});

test("an older response never overwrites a newer one", async () => {
  let releaseFirst;
  const first = new Promise(resolve => { releaseFirst = resolve; });
  let calls = 0;
  const ui = setup(url => {
    calls += 1;
    if (calls <= 2) {
      // The first pair (161 -> 237) answers late, with a different taxi fare.
      return first.then(() => ok(url.includes("rideshare") ? RIDESHARE : { ...TAXI, fare_avg: "99.00" }));
    }
    return byEndpoint(TAXI, RIDESHARE)(url);
  });
  ui.select(161, 237);
  ui.select(161, 132);
  await settle();
  releaseFirst();
  await settle();
  await settle();
  assert.equal(ui.text("rideshare-taxi-fare"), "$21.07");
});

test("a failed request shows an error, not stale numbers", async () => {
  const ui = setup(url =>
    url.startsWith("/api/routes/rideshare?")
      ? Promise.resolve({ ok: false, status: 500 })
      : ok(TAXI)
  );
  ui.select(161, 237);
  await settle();
  assert.equal(ui.text("rideshare-status"), "Could not load the taxi and rideshare comparison.");
  assert.equal(ui.text("rideshare-taxi-fare"), "—");
  assert.equal(ui.elements["rideshare-verdict"].hidden, true);
});
