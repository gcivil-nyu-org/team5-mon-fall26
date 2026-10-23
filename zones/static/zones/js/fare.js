// Fare range and trip duration component for US5 #7 and US6 #8.
// Both lines come from the same /api/routes response so they never
// disagree about whether there is enough data.
(function () {
  'use strict';

  const fareRange = document.getElementById('fare-range');
  const fareScope = document.getElementById('fare-scope');
  const tripDuration = document.getElementById('trip-duration');

  let pickup = null;
  let dropoff = null;
  let day = null;
  let hour = null;
  // Only the newest request may write the fare line.
  let fareSequence = 0;

  function dollars(value) {
    return `$${Number(value).toFixed(2)}`;
  }

  function loadFare() {
    const sequence = ++fareSequence;
    if (pickup === null || day === null) {
      fareRange.textContent = '—';
      fareScope.textContent = '';
      tripDuration.textContent = '—';
      return;
    }

    const params = new URLSearchParams({ from: pickup, day: day, hour: hour });
    if (dropoff !== null) params.set('to', dropoff);
    fareScope.textContent = dropoff === null
      ? 'All trips from this pickup zone'
      : 'Trips from the pickup to the dropoff zone';
    fareRange.textContent = 'Loading…';
    tripDuration.textContent = 'Loading…';

    fetch(`/api/routes?${params}`)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        if (sequence !== fareSequence) return;
        if (data.enough_data) {
          fareRange.textContent = `min ${dollars(data.fare_min)} · avg ${dollars(data.fare_avg)} · max ${dollars(data.fare_max)}`;
          tripDuration.textContent = `${Number(data.avg_duration_min).toFixed(1)} min`;
        } else {
          fareRange.textContent = 'Not enough data';
          tripDuration.textContent = 'Not enough data';
        }
      })
      .catch(error => {
        if (sequence !== fareSequence) return;
        console.error('Fare error:', error);
        fareRange.textContent = 'Could not load fare';
        tripDuration.textContent = 'Could not load duration';
      });
  }

  // The map's first load sets the starting day and hour.
  document.addEventListener('taxiscope:map-ready', function (e) {
    day = e.detail.data.day;
    hour = e.detail.data.hour;
    loadFare();
  });

  document.addEventListener('taxiscope:zones-selected', function (e) {
    pickup = e.detail.pickup;
    dropoff = e.detail.dropoff;
    loadFare();
  });

  // Sent by filters.js once the map shows the new day and hour.
  document.addEventListener('taxiscope:time-changed', function (e) {
    day = e.detail.day;
    hour = e.detail.hour;
    loadFare();
  });
})();
