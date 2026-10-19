// Heatmap component for US3: View Demand Heatmap
(function () {
  'use strict';

  const heatmapPanel = document.getElementById('heatmap-panel');
  const heatmapTitle = document.getElementById('heatmap-title');
  const heatmapContainer = document.getElementById('heatmap-container');
  const metricRadios = document.querySelectorAll('input[name="heatmap-metric"]');

  let currentZoneId = null;
  let currentData = null;

  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

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

  function loadHeatmap(zoneId, zoneName) {
    currentZoneId = zoneId;
    heatmapTitle.textContent = `${zoneName} - Weekly Demand`;

    fetch(`/api/zones/${zoneId}/heatmap`)
      .then(response => {
        if (!response.ok) {
          throw new Error('Failed to load heatmap');
        }
        return response.json();
      })
      .then(data => {
        currentData = data;
        const metric = document.querySelector('input[name="heatmap-metric"]:checked').value;
        renderHeatmap(data, metric);
        showHeatmap();
      })
      .catch(error => {
        console.error('Heatmap error:', error);
        heatmapContainer.innerHTML = '<p class="error">Failed to load heatmap data</p>';
      });
  }

  function renderHeatmap(data, metric) {
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
    const values = [];
    data.heatmap.forEach(day => {
      day.forEach(cell => {
        if (cell[metric] !== null) {
          values.push(cell[metric]);
        }
      });
    });
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);

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

        row.appendChild(cell);
      });

      grid.appendChild(row);
    });

    heatmapContainer.innerHTML = '';
    heatmapContainer.appendChild(grid);
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
    heatmapContainer.innerHTML = '';
  }
})();
