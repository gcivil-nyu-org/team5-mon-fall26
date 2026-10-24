// Run with: node --test zones/tests/trip_summary.test.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sources = ['trip-summary.js', 'fare.js', 'windows.js'].map(name =>
  fs.readFileSync(path.join(__dirname, '../static/zones/js', name), 'utf8')
);

function setup(fetch) {
  const ids = [
    'summary-panel', 'summary-toggle',
    'best-row', 'worst-row',
    'summary-route', 'summary-time',
    'windows-status',
    'fare-range', 'trip-duration', 'best-fare', 'best-duration',
    'worst-fare', 'worst-duration', 'pickup-zone', 'dropoff-zone',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, {
    hidden: true, textContent: '', listeners: {}, attributes: {},
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    click() { this.listeners.click(); },
  }]));
  const listeners = {};
  const document = {
    getElementById(id) { return elements[id]; },
    addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
  };
  for (const source of sources) {
    vm.runInNewContext(source, { document, fetch, URLSearchParams, Promise, Number, String,
      console: { error() {} } });
  }
  return {
    elements,
    emit(name, detail) { for (const listener of listeners[name]) listener({ detail }); },
    select(pickup, dropoff) {
      elements['pickup-zone'].textContent = 'Pickup';
      elements['dropoff-zone'].textContent = 'Dropoff';
      this.emit('taxiscope:zones-selected', { pickup, dropoff });
    },
  };
}

function routeResult(fare = '12.00') {
  return { enough_data: true, fare_min: '8.00', fare_avg: fare,
    fare_max: '20.00', avg_duration_min: 13.2 };
}

function windowsResult() {
  const slot = (hour, fare, duration) => ({ hour, fare_avg: fare, avg_duration_min: duration });
  return { enough_data: true,
    best: { fare: slot(3, '9.00', 6), duration: slot(4, '10.00', 5) },
    worst: { fare: slot(17, '18.00', 15), duration: slot(18, '17.00', 16) },
  };
}

const response = data => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
const settle = () => new Promise(resolve => setImmediate(resolve));

test('opens for a route, combines both APIs, and refreshes after a successful time change', async () => {
  const urls = [];
  const ui = setup(url => {
    urls.push(url);
    return response(url.startsWith('/api/routes/windows') ? windowsResult() : routeResult());
  });
  ui.emit('taxiscope:map-ready', { data: { day: 2, hour: 14 } });
  ui.select(237, null);
  await settle();
  assert.equal(ui.elements['summary-panel'].hidden, false);
  assert.equal(ui.elements['best-row'].hidden, true);
  assert.equal(urls.length, 1);
  assert.match(urls[0], /from=237&day=2&hour=14/);
  assert.equal(ui.elements['fare-range'].textContent, '$8.00 / $12.00 / $20.00');

  ui.select(237, 236);
  await settle();
  assert.equal(ui.elements['summary-panel'].hidden, false);
  assert.equal(ui.elements['best-row'].hidden, false);
  assert.equal(ui.elements['summary-toggle'].attributes['aria-expanded'], 'true');
  assert.match(ui.elements['fare-range'].textContent, /\$8\.00 \/ \$12\.00 \/ \$20\.00/);
  assert.equal(ui.elements['trip-duration'].textContent, '13.2 min');
  assert.match(ui.elements['best-fare'].textContent, /03:00/);
  assert.match(ui.elements['worst-duration'].textContent, /18:00/);
  assert.doesNotMatch(ui.elements['best-fare'].textContent, /Cheapest/);
  assert.doesNotMatch(ui.elements['summary-time'].textContent, /best\/worst across/);
  assert.match(urls[1], /day=2&hour=14&to=236/);
  assert.match(urls[2], /day=2/);

  ui.emit('taxiscope:time-changed', { day: 3, hour: 9 });
  await settle();
  assert.match(ui.elements['summary-time'].textContent, /Thursday 9:00/);
  assert.match(urls[3], /day=3&hour=9&to=236/);
  assert.match(urls[4], /day=3/);
});

test('collapse, expand, and clearing a route update visibility', async () => {
  const ui = setup(url => response(url.startsWith('/api/routes/windows') ? windowsResult() : routeResult()));
  ui.emit('taxiscope:map-ready', { data: { day: 0, hour: 10 } });
  ui.select(1, 2);
  await settle();
  ui.elements['summary-toggle'].click();
  assert.equal(ui.elements['summary-panel'].hidden, true);
  assert.equal(ui.elements['summary-toggle'].hidden, false);
  assert.equal(ui.elements['summary-toggle'].attributes['aria-expanded'], 'false');
  ui.elements['summary-toggle'].click();
  assert.equal(ui.elements['summary-panel'].hidden, false);
  assert.equal(ui.elements['summary-toggle'].attributes['aria-expanded'], 'true');
  ui.select(1, null);
  assert.equal(ui.elements['summary-panel'].hidden, false);
  assert.equal(ui.elements['best-row'].hidden, true);
  ui.select(null, null);
  assert.equal(ui.elements['summary-panel'].hidden, true);
  assert.equal(ui.elements['summary-toggle'].hidden, true);
});

test('an hour change refreshes fare without refetching day-wide windows', async () => {
  const urls = [];
  const ui = setup(url => {
    urls.push(url);
    return response(url.startsWith('/api/routes/windows') ? windowsResult() : routeResult());
  });
  ui.emit('taxiscope:map-ready', { data: { day: 2, hour: 14 } });
  ui.select(237, 236);
  await settle();
  ui.emit('taxiscope:time-changed', { day: 2, hour: 15 });
  await settle();
  assert.equal(urls.length, 3);
  assert.match(urls[2], /hour=15/);
  assert.equal(urls.filter(url => url.startsWith('/api/routes/windows')).length, 1);
  assert.match(ui.elements['summary-time'].textContent, /15:00/);
});

test('an older response cannot overwrite a changed route', async () => {
  const pending = [];
  const ui = setup(url => new Promise(resolve => pending.push({ url, resolve })));
  ui.emit('taxiscope:map-ready', { data: { day: 0, hour: 10 } });
  ui.select(1, 2);
  ui.select(1, 3);
  pending[2].resolve(response(routeResult('25.00')));
  pending[3].resolve(response(windowsResult()));
  await settle();
  assert.match(ui.elements['fare-range'].textContent, /\$25\.00/);
  pending[0].resolve(response(routeResult('11.00')));
  pending[1].resolve(response(windowsResult()));
  await settle();
  assert.match(ui.elements['fare-range'].textContent, /\$25\.00/);
});

test('distinguishes insufficient data from a failed request', async () => {
  const ui = setup(url => url.startsWith('/api/routes/windows')
    ? Promise.reject(new Error('offline'))
    : response({ enough_data: false }));
  ui.emit('taxiscope:map-ready', { data: { day: 0, hour: 10 } });
  ui.select(1, 2);
  await settle();
  assert.equal(ui.elements['fare-range'].textContent, 'Not enough data');
  assert.equal(ui.elements['trip-duration'].textContent, 'Not enough data');
  assert.equal(ui.elements['best-fare'].textContent, 'Unavailable');
  assert.equal(ui.elements['windows-status'].textContent, 'Could not load best and worst times');
});

test('restores the fare and duration load failure messages', async () => {
  const ui = setup(url => url.startsWith('/api/routes/windows')
    ? response(windowsResult())
    : Promise.reject(new Error('offline')));
  ui.emit('taxiscope:map-ready', { data: { day: 0, hour: 10 } });
  ui.select(1, 2);
  await settle();
  assert.equal(ui.elements['fare-range'].textContent, 'Could not load fare');
  assert.equal(ui.elements['trip-duration'].textContent, 'Could not load duration');
});
