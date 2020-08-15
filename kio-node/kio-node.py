"""App Entry Point.
Web application entry point.

"""
import os
import sys

from flask import Flask, jsonify, request

import uptime

from modules import utils

kio_version = 'v0.0.1d'

app = Flask(__name__)


@app.route('/')
def index() -> str:
    """App Index. """
    data = {
        'kio-node': kio_version
    }
    return jsonify(data)


@app.route('/status')
def status() -> str:
    """App status page"""
    data = {
        'kio-node': kio_version,
        'operational': True,
        'uptime': uptime.boottime().__str__()
    }
    return jsonify(data)


@app.route('/set-display')
def set_display() -> str:
    """API route for setting the Kio-Nodes Chromium to load a requested URL, and killing the old
       Chromium tab process.
    """
    url = request.args.get('url')
    set_url = False
    if url: 
        print('Requested URL:\t%s' % url)
        ret = utils.set_display(url)
        if ret:
            set_url = True
            # Remove the old tab procs
            utils.kill_old_tab_procs()

    data = {
        'kio-node': kio_version,
        'status': 'success',
        'set_url': set_url,
        'url': url,
    }
    return jsonify(data)


@app.route('/reboot')
def reboot() -> str:
    """API route for rebooting the Kio Node. """
    utils.shell('shutdown -r now')
    data = {
        'kio-node': kio_version,
        'status': 'success',
    }
    return jsonify(data)


if __name__ == '__main__':
    port = sys.argv[1]
    app.secret_key = 'super secret key'
    app.run(host="0.0.0.0", port=port, debug=True)

# End File: kio/kio-node/kio-node.py
