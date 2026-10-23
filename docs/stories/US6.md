# #8 US6: View Trip Duration
Status on GitHub: IN PROGRESS (branch `us6-trip-duration`)

As a commuter, I want to see the typical trip duration for my trip at the selected time so that I can plan around travel time as well as cost.

Developer Tasks
- Calculate trip duration from pickup and drop-off timestamps
- Add typical duration to the trip API response
- Display the duration in minutes next to the fare range

Acceptance Criteria 
- Typical trip duration is shown in minutes alongside the fare range
- The duration updates when the zones or the selected time change
- If there are too few trips, the app shows "Not enough data"

## Implementation notes (2026-10-23)
Trip duration was already in the `/api/routes` response as `avg_duration_min`,
added for US5 #7, so this story reused it rather than adding a new endpoint
or an API field.

- The duration line used to come from `/api/zones` (`filters.js`,
  `updatePickupStats()`), which does not apply `MIN_TRIP_COUNT` and always
  showed the *pickup zone's* duration, even with a dropoff selected. That is
  the mismatch Aleena flagged against the US5 fare line, which already read
  the gated, route-aware `/api/routes` response.
- Fix: `fare.js` now writes both the fare line and the duration line inside
  the same `/api/routes` response handler, keyed off the same `enough_data`
  flag, so the two lines can never disagree. `filters.js` no longer touches
  the duration line. The existing `fareSequence` guard (drops stale
  responses when the hour slider moves quickly) now covers duration too,
  since it is the same request.
- No API contract change and no new dependency.

