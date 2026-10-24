// US7 best and worst times, displayed in the US8 trip summary.
(function () {
  'use strict';

  const bestRow = document.getElementById('best-row');
  const worstRow = document.getElementById('worst-row');
  const bestFare = document.getElementById('best-fare');
  const bestDuration = document.getElementById('best-duration');
  const worstFare = document.getElementById('worst-fare');
  const worstDuration = document.getElementById('worst-duration');
  const status = document.getElementById('windows-status');

  let pickup = null;
  let dropoff = null;
  let day = null;
  // Only the newest request may write the section.
  let windowsSequence = 0;

  function hourRange(hour) {
    return `${String(hour).padStart(2, '0')}:00–${String(hour).padStart(2, '0')}:59`;
  }

  function fareText(slot) {
    return `${hourRange(slot.hour)} (avg $${Number(slot.fare_avg).toFixed(2)})`;
  }

  function durationText(slot) {
    return `${hourRange(slot.hour)} (${Number(slot.avg_duration_min).toFixed(1)} min)`;
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle('error', isError);
  }

  function loadWindows() {
    const sequence = ++windowsSequence;
    // Best and worst are for a trip, so both zones are needed.
    if (pickup === null || dropoff === null || day === null) {
      bestRow.hidden = true;
      worstRow.hidden = true;
      for (const value of [bestFare, bestDuration, worstFare, worstDuration]) {
        value.textContent = '—';
      }
      showStatus('');
      return;
    }

    const params = new URLSearchParams({ from: pickup, to: dropoff, day: day });
    bestRow.hidden = false;
    worstRow.hidden = false;
    for (const value of [bestFare, bestDuration, worstFare, worstDuration]) {
      value.textContent = 'Loading…';
    }
    showStatus('');

    fetch(`/api/routes/windows?${params}`)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        if (sequence !== windowsSequence) return;
        if (!data.enough_data) {
          for (const value of [bestFare, bestDuration, worstFare, worstDuration]) {
            value.textContent = 'Not enough data';
          }
          return;
        }
        bestFare.textContent = fareText(data.best.fare);
        bestDuration.textContent = durationText(data.best.duration);
        worstFare.textContent = fareText(data.worst.fare);
        worstDuration.textContent = durationText(data.worst.duration);
      })
      .catch(error => {
        if (sequence !== windowsSequence) return;
        console.error('Windows error:', error);
        for (const value of [bestFare, bestDuration, worstFare, worstDuration]) {
          value.textContent = 'Unavailable';
        }
        showStatus('Could not load best and worst times', true);
      });
  }

  // The map's first load sets the starting day.
  document.addEventListener('taxiscope:map-ready', function (e) {
    day = e.detail.data.day;
    loadWindows();
  });

  document.addEventListener('taxiscope:zones-selected', function (e) {
    pickup = e.detail.pickup;
    dropoff = e.detail.dropoff;
    loadWindows();
  });

  // Sent by filters.js once the map shows the new day and hour. The
  // windows cover the whole day, so only a new day needs a reload.
  document.addEventListener('taxiscope:time-changed', function (e) {
    if (e.detail.day === day) return;
    day = e.detail.day;
    loadWindows();
  });
})();
