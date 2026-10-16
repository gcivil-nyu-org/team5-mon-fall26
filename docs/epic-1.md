# #1 Epic1: Explore Zone Demand & Fares
Status on GitHub: OPEN

The shared foundation of the app. Lets any visitor, signed in or not,
pick a zone and see historical demand, fares, and trip duration for it.
Every other epic builds on this data layer.

Personas:
- Alex — Daily Commuter
- Priya — Budget Visitor
- Marcus — Taxi-vs-Rideshare Decider

Features / implementation:
- Interactive NYC taxi zone map (choropleth colored by demand), built from aggregated [TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)
- Zone selection opens an hour-by-day-of-week heatmap of trip volume and average trip duration
- Fare range (min/avg/max) for the selected zone and time window
- Time and day filter/scrub controls
- Trip duration display alongside fare
- Best/worst travel window calculation from historical patterns
- Trip summary panel combining fare, duration, and pattern data for a pickup/destination pair
- No account required — fully read-only (MVP)
