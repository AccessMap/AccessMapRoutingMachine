from flask import Flask, json, jsonify, request
import psycopg2

app = Flask(__name__, instance_relative_config=True)
# Get default config (main app dir config.py) or environment variables
app.config.from_object('config')
# Get instance config (hidden from git, is in app dir/instance/config.py)
# Overrides default config.py and environment variables settings
try:
    app.config.from_pyfile('config.py')
except IOError:
    pass

DB_HOST = app.config['DB_HOST']
DB_USER = app.config['DB_USER']
DB_PASS = app.config['DB_PASS']
DB_NAME = app.config['DB_NAME']
DB_PORT = app.config['DB_PORT']
ROUTING_TABLE = app.config['ROUTING_TABLE']


@app.route('/')
def index():
    return 'Hello World!'

@app.route('/route.json', methods=['GET'])
def route():
    #########################
    ### Process arguments ###
    #########################
    # latlon (required!)
    waypoints_input = request.args.get('waypoints', None)
    if waypoints_input is None:
        return "Bad request - waypoints parameter is required."
    waypoints_input_list = json.loads(waypoints_input)
    # Consume in pairs
    waypoints = zip(waypoints_input_list[0::2], waypoints_input_list[1::2])
    # Separate origin and destination from intermediate waypoints
    origin = waypoints.pop(0)
    dest = waypoints.pop()

    ########################################################
    ### Find sidewalks closest to origin and destination ###
    ########################################################
    routing_table = ROUTING_TABLE + '_vertices_pgr'

    point_sql = 'ST_Setsrid(ST_Makepoint({}, {}), 4326)'
    # Note that in geoJSON, the order is [lon, lat], so reversed order here
    origin_geom = point_sql.format(origin[1], origin[0])
    dest_geom = point_sql.format(dest[1], dest[0])

    closest_row_sql = ("SELECT id FROM {} ORDER BY ST_Distance(the_geom, "
                       "ST_Transform({}, 2926)) limit 1;")
    origin_query = closest_row_sql.format(routing_table, origin_geom)
    dest_query = closest_row_sql.format(routing_table, dest_geom)

    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS,
                            connect_timeout=15.)
    with conn:
        with conn.cursor() as curs:
            curs.execute(origin_query)
            start_node = int(curs.fetchone()[0])
        with conn.cursor() as curs:
            curs.execute(dest_query)
            end_node = int(curs.fetchone()[0])

    #################################
    ### Cost function and routing ###
    #################################
    # Default distance cost constant is 1
    kdist = request.args.get('dist', 1)
    # Default elevation cost constant is 4
    # FIXME: these costs need to be normalized (distance vs. elevation)
    kele = request.args.get('ele', 1e10)
    ### Cost function(s)
    # cost_fun = "ST_length(geom) + (k_ele * abs(geom.ele1 - geom.ele2))"
    dist_cost = '{} * ST_length(geom)'.format(kdist)
    # height_cost = '{} * ABS(ele_change)'.format(kele)
    # Instead, let's do a slope cost
    slope_cost = 'CASE ST_length(geom) WHEN 0 THEN 0 ELSE {} * POW(ABS(ele_change) / ST_length(geom), 4) END'.format(kele)
    cost_fun = ' + '.join([dist_cost, slope_cost])

    # node_start = 15307
    # node_end = 15308
    ### With start/end nodes, get optimal route
    pgr_sql = ("SELECT id,"
                       "source::integer,"
                       "target::integer,"
                       "{}::double precision AS cost"
                " FROM {}").format(cost_fun, ROUTING_TABLE)
    route_sql = ("SELECT ST_AsGeoJSON(ST_Transform(b.geom, 4326)), cost FROM "
                 "pgr_dijkstra('{}',{},{},{},{}) a LEFT JOIN "
                 "{} b ON (a.id2 = b.id)")
    route_query = route_sql.format(pgr_sql, start_node, end_node, 'false',
                                   'false', ROUTING_TABLE)
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS,
                            connect_timeout=15.)
    with conn:
        with conn.cursor() as curs:
            curs.execute(route_query)
            route_geoms = []
            costs = []
            for q_linestring, q_cost in curs.fetchall():
                if q_linestring is not None:
                    route_geoms.append(json.loads(q_linestring))
                    costs.append(q_cost)
            print costs
            print
            print "Costs total:"
            print sum(costs)
            print

    ############################
    ### Produce the response ###
    ############################
    # TODO: return JSON directions similar to Mapbox or OSRM so e.g. leaflet-routing-machine can be used
    '''
    Format:
    JSON hash with:
        origin: geoJSON Feature with Point geometry for start point of route
        destination: geoJSON Feature with Point geometry for end point of route
        waypoints: array of geoJSON Feature Points
        routes: array of routes in descending order (just 1 for now):
            summary: A short, human-readable summary of the route
            geometry: geoJSON LineString of the route (OSRM/Mapbox use
                      polyline, often)
            steps: array of route steps (directions/maneuvers)
                way_name: way along which travel proceeds
                direction: cardinal direction (e.g. N, SW, E, etc)
                maneuver: JSON object representing the maneuver
                    No spec yet, but will mirror driving directions:
                        type: string of type of maneuver (short) e.g. cross
                              left/right
                        location: geoJSON Point geometry of maneuver location
                        instruction: e.g.
                            turn left and cross <street> on near side


    TODO:
        Add these to routes:
            distance: distance of route in meters
        Add these to steps:
            distance: distance from step maneuver to next step
            heading: what is this for? Drawing an arrow maybe?
    '''
    origin_feature = {'type': 'Feature',
                      'geometry': {'type': 'Point',
                                   'coordinates': [origin[1], origin[0]]},
                      'properties': {}}

    dest_feature = {'type': 'Feature',
                    'geometry': {'type': 'Point',
                                 'coordinates': [dest[1], dest[0]]},
                    'properties': {}}
    waypoints_feature_list = []
    for waypoint in waypoints:
        waypoint_feature = {'type': 'Feature',
                            'geometry': {'type': 'Point',
                                         'coordinates': waypoint},
                            'properties': {}}
        waypoints_feature_list.append(waypoint_feature)

    # TODO: here's where to add alternative routes once we have them
    routes = []
    route = {}
    route['geometry'] = {'type': 'LineString',
                         'coordinates': []}
    # Route geometries look like [coord1, coord2], if we just concatenated then
    # coord2 from the first geometry is coord1 from the second - gotta exclude
    # the first one after the initial
    # FIXME: prepended and appended waypoints to fix bug - shouldn't
    #        pgrouting return them as part of the steps?
    route['geometry']['coordinates'].append([origin[1], origin[0]])
    route['geometry']['coordinates'].append(route_geoms[0]['coordinates'][0])
    for geom in route_geoms:
        # FIXME: this isn't quite what we want (likely has redundant points)
        #        instead, generate polyline in the SQL command
        route['geometry']['coordinates'].append(geom['coordinates'][1])
    route['geometry']['coordinates'].append([dest[1], dest[0]])

    # TODO: These are fake steps - get real ones from pgrouting!
    import random
    route['steps'] = []
    # FIXME: Prepended/appended fake steps to get to routing part
    # for i in range(len(route_geoms) - 1):
    for route_coord in route['geometry']['coordinates']:
        step = {}
        step['way_name'] = 'sidewalk name'
        step['direction'] = 'NW'
        maneuver = {}
        maneuver['type'] = random.choice(['turn', 'cross'])
        man_location = {'type': 'Point',
                        'coordinates': route_coord}
        maneuver['location'] = man_location
        maneuver['instruction'] = 'Continue along your path'
        step['maneuver'] = maneuver
        route['steps'].append(step)
    route['summary'] = 'A sidewalk route'

    routes.append(route)

    route_response = {}
    route_response['origin'] = origin_feature
    route_response['destination'] = dest_feature
    route_response['waypoints'] = waypoints_feature_list
    route_response['routes'] = routes

    return jsonify(route_response)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type, Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')

    return response


if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True)
