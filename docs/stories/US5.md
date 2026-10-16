# #7 US5: View Fare Range
Status on GitHub: OPEN

As a visitor, I want to see the minimum, average, and maximum fare for my trip at the selected time so that I know roughly what I will pay.

Developer Tasks
- Create an API endpoint that returns min/avg/max fare by pickup zone, destination zone, day, and hour
- Calculate fares from cleaned data so outliers do not distort the range
- Display the fare range in dollars
- Set a minimum number of trips needed before showing a fare range

Acceptance Criteria 
- With both zones selected, the min/avg/max fare for that trip and time is shown
- With only a pickup zone selected, the fare range for all trips from that zone is shown
- If there are too few trips, the app shows "Not enough data" instead of a number
- Displayed values match a manual check against the dataset



