# #7 US5: View Fare Range
Status on GitHub: OPEN

As a visitor, I want to see the minimum, average, and maximum fare for my trip at the selected time so that I know roughly what I will pay.

Already in place (from US4 #6)
- The selection panel shows the pickup zone's lowest and highest fare for the selected day and hour, read from `/api/zones`.
- It does not show the average, does not change when a drop-off zone is selected, and shows "Not enough data" only when a cell has no trips.

Developer Tasks
- Create `GET /api/routes?from=&to=&day=&hour=` (as in the high-level design). It returns min/avg/max fare, trip count, and average duration by pickup zone, destination zone, day, and hour. With only a pickup zone, it uses that zone's statistics.
- Calculate fares from cleaned data so outliers do not distort the range (done in the import, US0a #20; fares are before tip).
- Display the minimum, average, and maximum fare in dollars in the selection panel, using `/api/routes`
- Set a minimum number of trips needed before showing a fare range: 5 trips, as one setting (`MIN_TRIP_COUNT`) that US6 and US7 can share
- Refresh the fare range when the zones or the day and hour change.
- Let the rider choose a trip within the same zone as pickup: a "Trip within this zone" button in the panel sets the dropoff to the pickup zone (the API already supports `from == to`)

Acceptance Criteria
- With both zones selected, the min/avg/max fare for that trip and time is shown.
- With only a pickup zone selected, the fare range for all trips from that zone is shown.
- If there are too few trips (fewer than 5), the app shows "Not enough data" instead of a number.
- Displayed values match a manual check against the dataset
