from flask import Flask, json, jsonify, request
import psycopg2
from routing import routing_request

app = Flask(__name__, instance_relative_config=True)
# Get default config (main app dir config.py) or environment variables
app.config.from_object('config')
# Get instance config (hidden from git, is in app dir/instance/config.py)
# Overrides default config.py and environment variables settings
try:
    app.config.from_pyfile('config.py')
except IOError:
    pass
# Enables debug traceback for logging
app.config['PROPAGATE_EXCEPTIONS'] = True

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
    #####################
    # Process arguments #
    #####################
    # TODO: input validation - return reasonable HTTP errors on bad input.
    # latlon (required!)
    waypoints_input = request.args.get('waypoints', None)
    if waypoints_input is None:
        return 'Bad request - waypoints parameter is required.'
    waypoints_input_list = json.loads(waypoints_input)
    # Consume in pairs
    waypoints = zip(waypoints_input_list[0::2], waypoints_input_list[1::2])

    # Default distance cost constant is 1
    kdist = request.args.get('dist', 1)
    # Default elevation cost constant is 4
    kele = request.args.get('ele', 1e10)

    #################
    # request route #
    #################
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS,
                            connect_timeout=15.)
    route_response = routing_request(conn, ROUTING_TABLE, waypoints, kdist,
                                     kele)

    return jsonify(route_response)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type, Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')

    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
