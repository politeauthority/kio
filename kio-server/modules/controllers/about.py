"""About - Controller

"""
from datetime import timedelta
import os

import arrow

from flask import Blueprint, render_template, g
from flask import current_app as app

from .. import db
from ..collections.device_cmds import DeviceCmds as DeviceCmdsCollect


about = Blueprint('About', __name__, url_prefix='/about')


@about.route('/')
def index(scan_type: str=''):
    """About page."""
    data = {
        'active_page': 'about',
    }
    return render_template('about/index.html', **data)


@about.route('/debug')
def debug(scan_type: str=''):
    """Debug page."""
    envs = {
        'KIO_SERVER_CONFIG': os.environ.get('KIO_SERVER_CONFIG')
    }
    data = {
        'active_page': 'about',
        # 'options': g.options,
        'environment': envs,
    }
    return render_template('about/debug.html', **data)


@about.route('/command-log')
def command_log(scan_type: str=''):
    """Command Log"""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    collect = DeviceCmdsCollect(conn, cursor)
    one_hour_ago = (arrow.utcnow() - timedelta(hours=1)).datetime

    cmds = collect.get_since(one_hour_ago)

    print(cmds)
    data = {
        'active_page': 'about',
    }
    return render_template('about/command-log.html', **data)



# End File: kio/kio-server/modules/controllers/about.py
