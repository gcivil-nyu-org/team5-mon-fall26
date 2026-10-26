# #5 US3: View Demand Heatmap
Status on GitHub: OPEN

As a commuter, I want to see an hour-by-day-of-week heatmap of trip volume and average trip duration for my pickup zone so that I know when it is usually busy.

Developer Tasks
- Create an API endpoint that returns 7 x 24 aggregated values (trip volume and average trip duration) for a zone
- Build the heatmap component (days x hours)
- Add a toggle between trip volume and average trip duration
- Show the exact value on hover

Acceptance Criteria 
- Selecting a pickup zone displays a 7-day x 24-hour heatmap for that zone
- The user can switch between trip volume and average trip duration
- Hovering over a cell shows the exact value for that day and hour
- Cells with no data are clearly marked instead of showing zero

