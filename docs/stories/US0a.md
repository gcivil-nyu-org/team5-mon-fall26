# #20 US0a: Import TLC trips and build stats tables
Status on GitHub: OPEN

As the product team, we need one or more months of cleaned TLC yellow taxi trips aggregated into zone and route statistics in the database so every map, fare, and heatmap request is fast.

**Developer Tasks**
- Download NYC TLC yellow taxi trip file (Parquet)
- Load the taxi zone lookup (zone ID, name, borough) into `zone`
- Remove outlier trips (zero or negative fares, impossible distances and durations, voided trips, unknown zones)
- Aggregate by pickup zone, day of week, and hour into `zone_hour_stats`, and by pickup-dropoff pair into `route_hour_stats`
- Bulk load the results into PostgreSQL
- Produce an import report (rows kept, rows removed per cleaning rule)

**Acceptance Criteria**
- A monthly TLC file can be imported end to end with one command (`python manage.py import_trips --month YYYY-MM`)
- The import report shows how many rows were kept and removed
- `zone`, `zone_hour_stats`, and `route_hour_stats` are filled and queryable
- Running the same import twice does not create duplicate rows


