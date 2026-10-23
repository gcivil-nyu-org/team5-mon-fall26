// Best and worst times component for US7 #9: Find Best and Worst Travel Times.
// Reads /api/routes/windows for the selected zones and day.
(function () {
  'use strict';

  const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  const section = document.getElementById('windows');
  const dayLabel = document.getElementById('windows-day');
  const status = document.getElementById('windows-status');
  const list = document.getElementById('windows-list');
  const bestFare = document.getElementById('best-fare');
  const bestDuration = document.getElementById('best-duration');
  const worstFare = document.getElementById('worst-fare');
  const worstDuration = document.getElementById('worst-duration');

  let pickup = null;
  let dropoff = null;
  let day = null;
  // Only the newest request may write the section.
  let windowsSequence = 0;

  function hourRange(hour) {
    return `${hour}:00–${hour}:59`;
  }

  function fareText(slot) {
    return `${hourRange(slot.hour)} (avg $${Number(slot.fare_avg).toFixed(2)})`;
  }

  function durationText(slot) {
    return `${hourRange(slot.hour)} (${Number(slot.avg_duration_min).toFixed(1)} min)`;
  }

  function showStatus(message) {
    status.textContent = message;
    status.hidden = false;
    list.hidden = true;
  }

  function loadWindows() {
    const sequence = ++windowsSequence;
    if (pickup === null || day === null) {
      section.hidden = true;
      return;
    }

    const params = new URLSearchParams({ from: pickup, day: day });
    if (dropoff !== null) params.set('to', dropoff);
    dayLabel.textContent = DAYS[day];
    section.hidden = false;
    showStatus('Loading…');

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
          showStatus('Not enough data');
          return;
        }
        bestFare.textContent = fareText(data.best.fare);
        bestDuration.textContent = durationText(data.best.duration);
        worstFare.textContent = fareText(data.worst.fare);
        worstDuration.textContent = durationText(data.worst.duration);
        status.hidden = true;
        list.hidden = false;
      })
      .catch(error => {
        if (sequence !== windowsSequence) return;
        console.error('Windows error:', error);
        showStatus('Could not load best and worst times');
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
