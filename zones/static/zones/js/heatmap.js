// Heatmap component for US3: View Demand Heatmap
// US22 #69: the 7x24 grid drawing is shared through window.TaxiScopeHeatmap,
// so the compare page can draw two grids; the map's panel works as before.
// US29 #76: the "Show likely surge hours" toggle marks the zone's likely
// Uber/Lyft surge hours, from /api/zones/:id/surge, on the same grid.
(function () {
  'use strict';

  const heatmapPanel = document.getElementById('heatmap-panel');
  const heatmapTitle = document.getElementById('heatmap-title');
  const heatmapContainer = document.getElementById('heatmap-container');
  const metricRadios = document.querySelectorAll('input[name="heatmap-metric"]');
  const surgeToggle = document.getElementById('surge-toggle');
  const surgeLegend = document.getElementById('surge-legend');
  const surgeStatus = document.getElementById('surge-status');

  let currentZoneId = null;
  let currentData = null;
  // The surge grid of currentZoneId, once loaded; only the newest request wins.
  let surgeData = null;
  let surgeSequence = 0;

  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  window.TaxiScopeHeatmap = { renderGrid, valueRange };

  // Pages without the map's heatmap panel (the compare page) only use renderGrid.
  if (heatmapPanel) {
    // Listen for zone selection changes
    document.addEventListener('taxiscope:zones-selected', function (e) {
      if (e.detail.pickup) {
        // Pickup zone selected - load its heatmap
        // Get zone name from the pickup display element
        const zoneName = document.getElementById('pickup-zone').textContent;
        loadHeatmap(e.detail.pickup, zoneName);
      } else {
        // Pickup cleared
        hideHeatmap();
      }
    });

    // Listen for metric toggle
    metricRadios.forEach(radio => {
      radio.addEventListener('change', function () {
        if (currentData) {
          renderHeatmap(currentData, this.value);
        }
      });
    });

    if (surgeToggle) {
      surgeToggle.addEventListener('change', function () {
        surgeLegend.hidden = !this.checked;
        if (this.checked && currentZoneId !== null && surgeData === null) {
          loadSurge(currentZoneId);
        } else {
          rerender();
        }
      });
    }
  }

  function surgeOn() {
    return Boolean(surgeToggle && surgeToggle.checked);
  }

  function selectedMetric() {
    return document.querySelector('input[name="heatmap-metric"]:checked').value;
  }

  function rerender() {
    if (currentData) renderHeatmap(currentData, selectedMetric());
  }

  function countSurgeHours(data) {
    let count = 0;
    data.surge.forEach(day => day.forEach(cell => { if (cell.likely_surge) count += 1; }));
    return count;
  }

  function surgeSummary(data) {
    if (!data.enough_data) {
      return 'Not enough Uber/Lyft trips from this zone to estimate surge hours.';
    }
    const count = countSurgeHours(data);
    const typical = `typical $${Number(data.median_fare_per_mile).toFixed(2)} per mile`;
    if (count === 0) return `No likely surge hours this week (${typical}).`;
    return `${count} likely surge ${count === 1 ? 'hour' : 'hours'} this week (${typical}).`;
  }

  function loadSurge(zoneId) {
    const sequence = ++surgeSequence;
    surgeData = null;
    surgeStatus.textContent = 'Loading likely surge hours…';
    fetch(`/api/zones/${zoneId}/surge`)
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(data => {
        if (sequence !== surgeSequence || zoneId !== currentZoneId) return;
        surgeData = data;
        surgeStatus.textContent = surgeSummary(data);
        rerender();
      })
      .catch(error => {
        if (sequence !== surgeSequence) return;
        console.error('Surge error:', error);
        surgeStatus.textContent = 'Could not load likely surge hours.';
      });
  }

  function loadHeatmap(zoneId, zoneName) {
    currentZoneId = zoneId;
    heatmapTitle.textContent = `${zoneName} - Weekly Demand`;
    surgeData = null;
    if (surgeOn()) {
      loadSurge(zoneId);
    } else {
      ++surgeSequence; // a pending surge answer for the old zone is ignored
    }

    fetch(`/api/zones/${zoneId}/heatmap`)
      .then(response => {
        if (!response.ok) {
          throw new Error('Failed to load heatmap');
        }
        return response.json();
      })
      .then(data => {
        currentData = data;
        renderHeatmap(data, selectedMetric());
        showHeatmap();
      })
      .catch(error => {
        console.error('Heatmap error:', error);
        heatmapContainer.innerHTML = '<p class="error">Failed to load heatmap data</p>';
        showHeatmap();
      });
  }

  function renderHeatmap(data, metric) {
    const surge = surgeOn() && surgeData && surgeData.zone_id === currentZoneId ? surgeData : null;
    renderGrid(heatmapContainer, data, metric, { surge });
  }

  // Hover words for a likely surge cell: fare per mile and average wait.
  function surgeTitle(cell) {
    const wait = cell.avg_wait_min === null
      ? 'average wait: not enough data'
      : `average wait ${Number(cell.avg_wait_min).toFixed(1)} min`;
    return `Likely Uber/Lyft surge: $${Number(cell.fare_per_mile).toFixed(2)} per mile ` +
      `(${Number(cell.surge_ratio).toFixed(2)}× typical), ${wait}`;
  }

  // Smallest and largest value of a metric in a 7x24 heatmap, or null
  // when no cell has a value.
  function valueRange(data, metric) {
    const values = [];
    data.heatmap.forEach(day => {
      day.forEach(cell => {
        if (cell[metric] !== null) {
          values.push(cell[metric]);
        }
      });
    });
    if (values.length === 0) return null;
    return { min: Math.min(...values), max: Math.max(...values) };
  }

  // Draw a 7x24 grid into container. options.highlight ({day, hour})
  // outlines one cell; options.range ({min, max}) replaces the zone's own
  // min and max, so two grids can share one colour scale; options.surge
  // (a /api/zones/:id/surge response) marks its likely surge cells.
  function renderGrid(container, data, metric, options = {}) {
    const grid = document.createElement('div');
    grid.className = 'heatmap-grid';

    // Add hour labels across the top
    const headerRow = document.createElement('div');
    headerRow.className = 'heatmap-row heatmap-header';
    const cornerCell = document.createElement('div');
    cornerCell.className = 'heatmap-day-label';
    headerRow.appendChild(cornerCell);
    for (let hour = 0; hour < 24; hour++) {
      const hourLabel = document.createElement('div');
      hourLabel.className = 'heatmap-hour-label';
      hourLabel.textContent = hour;
      headerRow.appendChild(hourLabel);
    }
    grid.appendChild(headerRow);

    // Find min/max for color scaling
    const range = options.range || valueRange(data, metric);
    const minVal = range ? range.min : Infinity;
    const maxVal = range ? range.max : -Infinity;
    const highlight = options.highlight;
    const surge = options.surge || null;

    // Add 7 day rows
    data.heatmap.forEach((dayData, dayIndex) => {
      const row = document.createElement('div');
      row.className = 'heatmap-row';

      // Day label
      const dayLabel = document.createElement('div');
      dayLabel.className = 'heatmap-day-label';
      dayLabel.textContent = DAY_LABELS[dayIndex];
      row.appendChild(dayLabel);

      // 24 hour cells
      dayData.forEach((cellData, hourIndex) => {
        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';

        if (cellData[metric] === null) {
          cell.classList.add('no-data');
          cell.title = `${DAY_LABELS[dayIndex]} ${hourIndex}:00 - No data`;
        } else {
          const value = cellData[metric];
          const intensity = (value - minVal) / (maxVal - minVal || 1);
          cell.style.backgroundColor = getColor(intensity);

          const displayValue = metric === 'trip_count'
            ? Math.round(value).toLocaleString()
            : `${value.toFixed(1)} min`;

          cell.title = `${DAY_LABELS[dayIndex]} ${hourIndex}:00\n${displayValue}`;
          cell.textContent = ''; // No text inside, just color
        }
        if (highlight && highlight.day === dayIndex && highlight.hour === hourIndex) {
          cell.classList.add('is-selected');
        }
        const surgeCell = surge ? surge.surge[dayIndex][hourIndex] : null;
        if (surgeCell && surgeCell.likely_surge) {
          cell.classList.add('is-surge');
          cell.title = `${cell.title}\n${surgeTitle(surgeCell)}`;
        }

        row.appendChild(cell);
      });

      grid.appendChild(row);
    });

    container.innerHTML = '';
    container.appendChild(grid);
  }

  function getColor(intensity) {
    // Blue (low) to red (high)
    const r = Math.round(intensity * 255);
    const b = Math.round((1 - intensity) * 255);
    const g = 50;
    return `rgb(${r}, ${g}, ${b})`;
  }

  function showHeatmap() {
    heatmapPanel.hidden = false;
  }

  function hideHeatmap() {
    heatmapPanel.hidden = true;
    currentZoneId = null;
    currentData = null;
    surgeData = null;
    ++surgeSequence;
    if (surgeStatus) surgeStatus.textContent = '';
    heatmapContainer.innerHTML = '';
  }
})();
