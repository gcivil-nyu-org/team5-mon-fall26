// US28 #75: "Taxi vs. rideshare" in the trip summary.
// Taxi from /api/routes, Uber/Lyft from /api/routes/rideshare, for the
// selected pickup, dropoff, day and hour. Both are fetched together, so
// the two columns and the "which was cheaper" line always describe the
// same request. Shown only for a trip (pickup and dropoff), like US7.
(function () {
  'use strict';

  const panel = document.getElementById('rideshare-panel');
  const status = document.getElementById('rideshare-status');
  const verdict = document.getElementById('rideshare-verdict');
  const cells = {
    taxi: {
      fare: document.getElementById('rideshare-taxi-fare'),
      range: document.getElementById('rideshare-taxi-range'),
      duration: document.getElementById('rideshare-taxi-duration'),
    },
    rideshare: {
      fare: document.getElementById('rideshare-ride-fare'),
      range: document.getElementById('rideshare-ride-range'),
      duration: document.getElementById('rideshare-ride-duration'),
      wait: document.getElementById('rideshare-ride-wait'),
    },
  };

  let pickup = null;
  let dropoff = null;
  let day = null;
  let hour = null;
  // Only the newest request may write the section.
  let sequence = 0;

  function dollars(value) {
    return `$${Number(value).toFixed(2)}`;
  }

  function minutes(value) {
    return `${Number(value).toFixed(1)} min`;
  }

  // Fares come from the API as strings with two decimals; compare whole
  // cents, the precision shown, so "$0.00 cheaper" can never appear.
  function cents(value) {
    return Math.round(Number(value) * 100);
  }

  function setAll(text) {
    for (const side of Object.values(cells)) {
      for (const cell of Object.values(side)) cell.textContent = text;
    }
  }

  function showSide(side, data) {
    const target = cells[side];
    if (!data.enough_data) {
      for (const cell of Object.values(target)) cell.textContent = 'Not enough data';
      return;
    }
    target.fare.textContent = dollars(data.fare_avg);
    target.range.textContent = `${dollars(data.fare_min)}–${dollars(data.fare_max)}`;
    target.duration.textContent = minutes(data.avg_duration_min);
    if (target.wait) {
      target.wait.textContent = data.avg_wait_min === null ? 'Not enough data' : minutes(data.avg_wait_min);
    }
  }

  // The "which was cheaper" sentence, or null when either side lacks data.
  function compare(taxi, rideshare) {
    if (!taxi.enough_data || !rideshare.enough_data) return null;
    const taxiCents = cents(taxi.fare_avg);
    const rideCents = cents(rideshare.fare_avg);
    if (taxiCents === rideCents) {
      return { cheaper: 'same', text: 'Taxi and Uber/Lyft had the same average fare at this time.' };
    }
    const cheaper = taxiCents < rideCents ? 'taxi' : 'rideshare';
    const difference = Math.abs(taxiCents - rideCents);
    const percent = Math.round((difference / Math.max(taxiCents, rideCents)) * 100);
    const name = cheaper === 'taxi' ? 'Taxi' : 'Uber/Lyft';
    return {
      cheaper,
      text: `${name} was cheaper at this time, by ${dollars(difference / 100)} on average (${percent}% less).`,
    };
  }

  function getJson(url) {
    return fetch(url).then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
  }

  function load() {
    const current = ++sequence;
    if (pickup === null || dropoff === null) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    if (day === null || hour === null) return;

    const params = new URLSearchParams({ from: pickup, to: dropoff, day: day, hour: hour });
    setAll('Loading…');
    verdict.hidden = true;
    verdict.textContent = '';
    status.textContent = '';

    Promise.all([getJson(`/api/routes?${params}`), getJson(`/api/routes/rideshare?${params}`)])
      .then(([taxi, rideshare]) => {
        if (current !== sequence) return;
        showSide('taxi', taxi);
        showSide('rideshare', rideshare);
        const result = compare(taxi, rideshare);
        if (result) {
          verdict.textContent = result.text;
          verdict.dataset.cheaper = result.cheaper;
          verdict.hidden = false;
        } else {
          status.textContent = 'Both need at least 5 past trips at this time to say which was cheaper.';
        }
      })
      .catch(error => {
        if (current !== sequence) return;
        console.error('Rideshare comparison error:', error);
        setAll('—');
        status.textContent = 'Could not load the taxi and rideshare comparison.';
      });
  }

  // The map's first load sets the starting day and hour.
  document.addEventListener('taxiscope:map-ready', function (e) {
    day = e.detail.data.day;
    hour = e.detail.data.hour;
    load();
  });

  document.addEventListener('taxiscope:zones-selected', function (e) {
    pickup = e.detail.pickup;
    dropoff = e.detail.dropoff;
    load();
  });

  // Sent by filters.js once the map shows the new day and hour.
  document.addEventListener('taxiscope:time-changed', function (e) {
    day = e.detail.day;
    hour = e.detail.hour;
    load();
  });
})();
