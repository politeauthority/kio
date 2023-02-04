"""Urls Controller

"""
from flask import Blueprint, render_template, request, redirect
from flask import current_app as app

from kio_server.utils import db
from kio_server.models.url import Url as UrlModel
from kio_server.collections.urls import Urls as UrlsCollect


urls = Blueprint('Urls', __name__, url_prefix='/urls')


@urls.route('/')
def index() -> str:
    """Urls roster page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    curls = UrlsCollect(conn, cursor)
    all_urls = curls.get_all()
    data = {
        "urls": all_urls,
        "urls_total": len(all_urls),
        "active_page": "urls"

    }
    return render_template('urls/dashboard.html', **data)

@urls.route('info/<url_id>')
def info(url_id: int) -> str:
    """Url info page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    url = UrlModel(conn, cursor)
    url.get_by_id(url_id)
    data = {
        "url": url
    }
    return render_template('urls/info.html', **data)


@urls.route('/create')
def create() -> str:
    """Create Device form."""
    data = {}
    data['form'] = 'new'
    data['url'] = None
    return render_template('urls/create.html', **data)


@urls.route('/save', methods=['POST'])
def save():
    """Device save, route for new and editing devices."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    url = UrlModel(conn, cursor)
    if request.form['url_id'] != 'new':
        url.get_by_id(request.form['url_id'])
        if not url.id:
            return 'ERROR 404: Route this to page_not_found method!', 404

    url.name = request.form['url_name']
    url.address = request.form['url_address']
    url.save()

    return redirect('/urls/info/%s' % url.id)

# End File: kio/kio-server/modules/controllers/urls.py
