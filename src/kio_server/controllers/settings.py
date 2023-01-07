"""Setting Controller

"""
import logging

from flask import Blueprint, render_template, redirect, request, g, session
from flask import current_app as app

from kio_server.utils import db
from kio_server.models.option import Option

settings = Blueprint('Settings', __name__, url_prefix='/settings')


@settings.route('/')
@settings.route('/general')
def form_general() -> str:
    """Setting page."""
    data = {
        'active_page': 'settings',
        'active_page_sub': 'general',
        # 'settings': g.options,
    }
    return render_template('settings/form_general.html', **data)


@settings.route('/save-general', methods=['POST'])
def save_general():
    """General settings save."""
    conn, cursor = db.connect_mysql(app.config['LAN_NANNY_DB'])

    # Update System Name
    _save_setting(conn, cursor, 'system-name', request.form['setting_system_name'])

    # Update timezone
    _save_setting(conn, cursor, 'timezone', request.form['settings_timezone'])

    # Update console-ui-color
    _save_setting(conn, cursor, 'console-ui-color', request.form['settings_console_ui_color'])

    # Save "active-timeout"
    _save_setting(conn, cursor, 'active-timeout', request.form['setting_active_timeout'])

    # Save auto-reload-console
    _save_setting(conn, cursor, 'auto-reload-console', request.form['setting_auto_reload_console'])

    # Save beta-features
    _save_setting(conn, cursor, 'beta-features', request.form['setting_beta_features'])
    # If beta features are being disabled, disable alerts as well. @todo: when alerts leave beta,
    # pull this!
    if request.form['setting_beta_features'] == 'false':
        _save_setting(conn, cursor, 'alerts-enabled', 'false')

    # Save debug-features
    _save_setting(conn, cursor, 'debug-features', request.form['setting_debug_features'])

    return redirect('/settings')



# End File: kio/kio-server/modules/controllers/settings.py
