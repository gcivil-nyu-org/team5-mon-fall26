# #3 US1: View Taxi Demand Map
Status on GitHub: OPEN

As a visitor, I want to view an interactive map of NYC taxi zones colored by taxi demand so that I can see which areas are busy or quiet.

Developer Tasks
- Load the NYC taxi zone boundaries (TLC taxi zone shapefile/GeoJSON)
- Render the zones on an interactive map
- Compute trip volume per zone from the aggregated TLC data
- Color each zone by trip volume and add a legend
- Show the zone name and borough on hover

Acceptance Criteria 
- All NYC taxi zones appear on the map with visible boundaries
- Zones are colored by trip volume, and the legend explains what each color means.
- Hovering over a zone shows its name and borough
- The map loads in a few seconds and can be zoomed and panned

