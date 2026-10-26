# #9 US7: Find Best and Worst Travel Times
Status on GitHub: OPEN

As a commuter, I want to see the best and worst times to take my trip so that I can shift my departure when I have flexibility.

Developer Tasks
- Rank the hours of the selected day by typical fare and trip duration
- Agree with the Product Owner on how "best" and "worst" are defined (e.g., lowest/highest fare and duration)
- Highlight the best and worst time windows in the UI

Acceptance Criteria 
- The best and worst time windows are shown for the selected trip and day
- Best and worst windows are clearly labeled and visually distinct.
- Results are labeled as based on historical data, not guaranteed
- The ranking matches the underlying aggregated data


## Implementation notes (2026-10-23)
- **Rule (proposed, to confirm with the PO):** the story's example, lowest/highest fare and duration. Hours are ranked by average fare and by average duration separately. Best = cheapest and fastest hour, worst = most expensive and slowest. Ties go to the earlier hour. See `docs/decisions.md`.
- **API:** `GET /api/routes/windows?from=&to=&day=` (`zones/stats.py` `route_windows()`, `zones/views.py`). Same tables and `MIN_TRIP_COUNT` as `/api/routes`.
- **UI:** "Best and worst times" section in the selection panel (`zones/static/zones/js/windows.js`), labeled Best (green) and Worst (red), with "Based on past trips (March–May 2026), not a guarantee." Shown only once a pickup and a dropoff are both selected (team decision).
