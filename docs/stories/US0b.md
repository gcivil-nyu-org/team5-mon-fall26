# #21 US0b: Taxi zone shapes
Status on GitHub: OPEN

As the product team, we need the taxi zone boundaries as a static GeoJSON file, so the map can draw zones without PostGIS.

**Developer Tasks**
- Download the TLC taxi zone shapefile
- Convert it to GeoJSON in latitude/longitude (WGS84)
- Commit the file to `zones/data/` and document how it was made so it can be regenerated

**Acceptance Criteria**
- The GeoJSON contains every zone in the TLC shapefile
- Each shape's `LocationID` matches `zone.zone_id` in the database
- The file loads in Leaflet with zones drawn in the right place
