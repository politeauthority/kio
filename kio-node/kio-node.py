"""App Entry Point.
Web application entry point.

"""
import os
import sys

from flask import Flask, jsonify, request

from modules import utils

kio_version = 'v0.0.1'

app = Flask(__name__)


@app.route('/')
def index() -> str:
    """ App Index."""
    data = {
        'Kio-Node': kio_version
    }
    return jsonify(data)


@app.route('/status')
def status() -> str:
    """ App Index."""
    data = {
        'Kio-Node': kio_version
        'operational': True
    }
    return jsonify(data)


@app.route('/set-display')
def set_display() -> str:
    """ App Index."""
    url = request.args.get('url')
    set_url = False
    if url: 
        print('Requested URL:\t%s' % url)
        ret = utils.set_display(url)
        if ret:
            set_url = True

    data = {
        'Kio-Node': kio_version
        'status': 'success',
        'set_url': set_url,
        'url': url
    }
    return jsonify(data)



if __name__ == '__main__':
    port = sys.argv[1]
    app.secret_key = 'super secret key'
    app.run(host="0.0.0.0", port=port, debug=True)

# End File: kio/kio-node/kio-node.py
