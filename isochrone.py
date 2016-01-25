import json


def isochrone_data(conn, lonlat):
    '''Calculates ST_drivingDistance using the routing cost function for use in
    displaying isochrones.

    :param conn: psycopg2 connection to the routing database.
    :type conn: psycopg2.connection
    :param lonlat: Lon-lat (geoJSON) coordinates of isochrone center.
    :type lonlat: list

    '''
    #############################################
    ### Find node closest to isochrone center ###
    #############################################

    lon = float(lonlat[0])
    lat = float(lonlat[1])
    point = 'ST_Setsrid(ST_Makepoint({}, {}), 4326)'.format(lon, lat)

    closest_node_sql = '''
      SELECT id
        FROM routing_nodes
    ORDER BY ST_Distance(geom, ST_Transform({}, 2926))
       LIMIT 1;
    '''.format(point)

    with conn:
        with conn.cursor() as curs:
            curs.execute(closest_node_sql)
            start_node = int(curs.fetchone()[0])

    isochrone_sql = """
    SELECT seq,
           id1 AS node,
           id2 AS edge,
           cost,
           ST_AsGeoJSON(geom) AS geom
      FROM pgr_drivingDistance(
           'SELECT id,
                   source,
                   target,
                   cost
              FROM routing',
           %s,
           10000,
           false,
           false) AS di
      JOIN routing_nodes AS pt
        ON di.id1 = pt.id;
    """

    with conn:
        with conn.cursor() as curs:
            curs.execute(isochrone_sql, (start_node,))
            isochrone_nodes = list(curs.fetchall())

    geom_fc = {'type': 'FeatureCollection',
               'features': []}
    for node in isochrone_nodes:
        feature = {'type': 'Feature',
                   'geometry': json.loads(node[-1]),
                   'properties': {'cost': node[-2]}}
        geom_fc['features'].append(feature)

    ############################
    ### Produce the response ###
    ############################

    return geom_fc
