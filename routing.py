import json


def routing_request(conn, routing_table, waypoints, kdist, kele):
    '''Process a routing request, returning a Mapbox-compatible routing JSON
    object.

    :param conn: psycopg2 connection to the routing database.
    :type conn: psycopg2.connection
    :param routing_table: the name of the routing table.
    :type routing_table: str
    :param origin: Trip origin (start) - lat, lon coords
    :type origin: list
    :param dest: Trip destination (end) - lat, lon coords
    :type dest: list
    :param kdist: Cost param for distance
    :type kdist: float
    :param kele: Cost param for elevation
    :type kele: float

    '''
    # Isolate first and last points
    origin = waypoints.pop(0)
    dest = waypoints.pop()
    ########################################################
    ### Find sidewalks closest to origin and destination ###
    ########################################################
    routing_vertices_table = routing_table + '_vertices_pgr'

    # BIG FIXME: WOW, these aren't injection safe at all (Bobby Tables...)
    point_sql = 'ST_Setsrid(ST_Makepoint({}, {}), 4326)'
    # Note that in geoJSON, the order is [lon, lat], so reversed order here
    origin_geom = point_sql.format(origin[1], origin[0])
    dest_geom = point_sql.format(dest[1], dest[0])

    # FIXME: The closest node to the selected point is not actually what we
    # want - that ends up with weird backtracking scenarios. What we want is
    # something like a new virtual node on the closest edge - i.e. the closest
    # realistic start point in the real world. I haven't been able to find a
    # pre-built solution for this in pgRouting. pgr_trsp can start and end at
    # edges + a distance along that edge, but it may not work easily with
    # custom cost functions (verify that). We can also roll our own option.
    # It will add some complication, as we'll need to calculate costs for the
    # two virtual edges of our virtual node. To do that super accurately, we'd
    # need to go back to the functions used to label data and apply them again
    # or approximate new costs (or attributes) on the virtual edges.
    # FIXME: Once closest-edge selection is implemented, remember to include
    # sidewalk edges and corners and disclude crossing edges.
    closest_row_sql = '''  SELECT id
                             FROM {}
                         ORDER BY ST_Distance(the_geom, ST_Transform({}, 2926))
                            LIMIT 1;'''
    origin_query = closest_row_sql.format(routing_vertices_table, origin_geom)
    dest_query = closest_row_sql.format(routing_vertices_table, dest_geom)

    with conn:
        with conn.cursor() as curs:
            curs.execute(origin_query)
            start_node = int(curs.fetchone()[0])
        with conn.cursor() as curs:
            curs.execute(dest_query)
            end_node = int(curs.fetchone()[0])

    print start_node, end_node
    #################################
    ### Cost function and routing ### #################################
    # FIXME: these costs need to be normalized (distance vs. elevation)
    ### Cost function(s)
    # cost_fun = 'ST_length(geom) + (k_ele * abs(geom.ele1 - geom.ele2))'
    dist_cost = '{} * ST_length(geom)'.format(kdist)
    # height_cost = '{} * ABS(ele_change)'.format(kele)
    # Instead, let's do a slope cost
    slope_cost = 'CASE ST_length(geom) WHEN 0 THEN 0 ELSE {} * POW(ABS(ele_change) / ST_length(geom), 4) END'.format(kele)
    cost_fun = ' + '.join([dist_cost, slope_cost])
    print cost_fun

    ###########################################
    # With start/end nodes, get optimal route #
    ###########################################
    # node_start = 15307
    # node_end = 15308
    # Origin and Destination nodes in pgRouting vertex table
    pgr_sql = '''SELECT id,
                        source::integer,
                        target::integer,
                        {}::double precision AS cost
                   FROM {};'''.format(cost_fun, routing_table)
    # Request route - turn geometries directly into GeoJSON
    route_sql = '''SELECT seq,
                          id1::integer AS node,
                          id2::integer AS edge,
                          cost
                     FROM pgr_dijkstra('{}',{},{},{},{});'''
    route_query = route_sql.format(pgr_sql, start_node, end_node, 'false',
                                   'false', routing_table)
    q_ids = []
    with conn:
        with conn.cursor() as curs:
            curs.execute(route_query)
            rows = list(curs.fetchall())
            # route_geoms = []
            # costs = []
            # for q_id, q_linestring, q_cost in curs.fetchall():
            #     q_ids.append(q_id)
            #     if q_linestring is not None:
            #         route_geoms.append(json.loads(q_linestring))
            #         costs.append(q_cost)
            # print costs
            # print
            # print 'Costs total:'
            # print sum(costs)
            # print

    geom_fc = {'type': 'FeatureCollection',
               'features': []}
    geoms = []
    for row in rows:
        with conn.cursor() as curs:
            args = {}
            node_id = row[1]
            edge_id = row[2]

            if edge_id != -1:
                geom_query = '''
                    SELECT ST_AsGeoJSON(ST_Transform(geom, 4326)),
                           ST_AsText(ST_Transform(geom, 4326))
                      FROM {}
                     WHERE source = {} AND id = {}
                     UNION
                    SELECT ST_AsGeoJSON(ST_Transform(ST_Reverse(geom), 4326)),
                           ST_AsText(ST_Transform(ST_Reverse(geom), 4326))
                      FROM {}
                     WHERE target = {} AND id = {};
                '''.format(routing_table, node_id, edge_id, routing_table,
                           node_id, edge_id)
                curs.execute(geom_query)
                geom_row = curs.fetchone()
                feature = {'type': 'Feature',
                           'geometry': json.loads(geom_row[0]),
                           'properties': {}}
                geom_fc['features'].append(feature)
                geom = 'ST_GeomFromText(\'{}\')'.format(geom_row[1])
                geoms.append(geom)

    geom_array_args = ', '.join(geoms)
    print json.dumps(geom_fc)
    print geom_array_args

    # Take geoms and join them into one big linestring
    merge_query = '''
        SELECT ST_AsGeoJSON(ST_LineMerge(ST_Union(ST_Collect(ARRAY[{}]))));
    '''.format(geom_array_args)
    with conn.cursor() as curs:
        curs.execute(merge_query)
        coords = json.loads(curs.fetchone()[0])['coordinates']

    # # Retrieve the node geometries for the route!
    # node_query = '''SELECT ST_AsGeoJSON(ST_Transform(the_geom, 4326))
    #                   FROM {}
    #                  WHERE id IN %(node_ids)s;'''
    # node_query = node_query.format(routing_vertices_table)
    # with conn:
    #     with conn.cursor() as curs:
    #         curs.execute(node_query, {'node_ids': nodes})
    #         node_geoms = list(curs.fetchall())

    # # Process node geom GeoJSON points into linestrings
    # node_coords = []
    # for row in node_geoms:
    #     feature = row[0]
    #     feature_json = json.loads(feature)
    #     node_coords.append(feature_json['coordinates'])

    # print node_coords

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
            summary: A short, human-readable summary of the route. DISABLED.
            geometry: geoJSON LineString of the route (OSRM/Mapbox use
                      polyline, often)
            steps: optional array of route steps (directions/maneuvers).
                   (NOT IMPLEMENTED YET)
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
    # Origin coordinates (start)
    route['geometry']['coordinates'].append([origin[1], origin[0]])
    # Route coordinates
    route['geometry']['coordinates'] += coords
    # for geom in route_geoms:
    #     # FIXME: this isn't quite what we want (likely has redundant points)
    #     #        instead, generate polyline in the SQL command
    #     for coord in geom['coordinates']:
    #         route['geometry']['coordinates'].append(coord)
    # Destination coordinates (end)
    route['geometry']['coordinates'].append([dest[1], dest[0]])

    # TODO: Add steps!
    route['steps'] = []
    route['summary'] = ''

    routes.append(route)

    route_response = {}
    route_response['origin'] = origin_feature
    route_response['destination'] = dest_feature
    route_response['waypoints'] = waypoints_feature_list
    route_response['routes'] = routes

    return route_response
