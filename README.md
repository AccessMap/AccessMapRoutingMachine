# simple routing server
## a prototype for AccessMap's routing server.

### Overview

Creates an endpoint at localhost:5000/route.json with these URL params:
* waypoints: a list of waypoints (maximum 2 right now) e.g. [lat1, lon1, lat2, lon2]

Returns directions as a JSON file of a format nearly identical to that used by Mapbox.

### Installation and Configuration
Install the python dependencies found in requirements.txt

copy config.py into a directory named 'instance' in the main project directory
and update the entries to match your database. Your routable (PostGIS, pgRouting-enabled)
table needs to have the following columns:
    id: unique key
    geom: a geometry (PostGIS LineString) describing the original data set pieces
    ele_change: Change in elevation (double precision)

Launch with python app.py
