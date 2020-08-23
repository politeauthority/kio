"""App Entry Point.
Web application entry point.

"""
import os
import sys

from flask import Flask, jsonify, request
import uptime

from modules import utils

kio_version = 'v0.0.2'
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


@app.route('/display-set')
def display_set() -> str:
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
            utils.kill_old_tabs()

    data = {
        'kio-node': kio_version,
        'status': 'success',
        'set_url': set_url,
        'url': url,
    }
    return jsonify(data)


@app.route('/toggle-display')
def display_toggle() -> str:
    """API route to turn on  or off the display. Keep in mind, the Kio-Node does not keep track of
       the state of the display on it's own.
    """
    # Get the display service
    display_service = request.args.get('service')
    if not display_service:
        display_service = "vcgencmd display_power"
    elif display_service == 'tvservice':
        display_service = 'tvservice'

    # Get the value we're setting the display to
    display_value = request.args.get('value')
    cmd_value = 1
    if str(display_value) in ['0', 'off', 'false']:
        cmd_value = 0

    # Set the proper value str based on the display service being accessed.
    if display_service == 'tvservice':
        if cmd_value == 1:
            cmd_value = '--preferred'
        else:
            cmd_value = '--off'

    # Run the command and report the results
    result = utils.shell('%s %s' % (display_service, cmd_value))
    status = 'success'
    if not result:
        status = 'failed'

    data = {
        'display_service': display_service,
        'value': cmd_value,
        'status': status
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
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = 7001
    app.secret_key = 'super secret key'
    app.run(host="0.0.0.0", port=port, debug=True)

# End File: kio/kio-node/kio-node.py
