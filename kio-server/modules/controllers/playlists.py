"""Playlists Controller

"""
from flask import Blueprint, render_template, redirect
from flask import current_app as app

from .. import db
from ..models.playlist import Playlist as PlaylistModel
from ..collections.playlists import Playlists as PlaylistsCollect
from ..collections.urls import Urls as UrlsCollect


playlists = Blueprint('Playlists', __name__, url_prefix='/playlists')



@playlists.route('/')
def index() -> str:
    """Urls roster page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    c_playlists = PlaylistsCollect(conn, cursor)
    all_pls = c_playlists.get_all()
    data = {
        "playlists": all_pls,
        "playlists_total": len(all_pls),
        "active_page": "playlists"

    }
    print(data)
    return render_template('playlists/dashboard.html', **data)

@playlists.route('info/<playlist_id>')
def info(playlist_id: int) -> str:
    """Playlist info page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    pl = PlaylistModel(conn, cursor)
    pl.get_by_id(playlist_id)
    urls = pl.get_urls()
    print(pl)
    data = {
        "playlist": pl,
        "urls": urls
    }
    return render_template('playlists/info.html', **data)


@playlists.route('edit/<playlist_id>')
def edit(playlist_id: int) -> str:
    """Playlist edit page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    pl = PlaylistModel(conn, cursor)
    pl.get_by_id(playlist_id)
    urls = pl.get_urls()
    flat_urls = flatten_urls(urls)

    c_urls = UrlsCollect(conn, cursor)
    all_urls = c_urls.get_all()
    print(pl)
    data = {
        "playlist": pl,
        "urls": urls,
        "all_urls": all_urls,
        "flat_urls": flat_urls
    }
    return render_template('playlists/edit.html', **data)


@playlists.route('quick-save-remove-url/<playlist_id>/<url_id>')
def qs_remove_url(playlist_id: int, url_id: int) -> str:
    """Playlist edit page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    pl = PlaylistModel(conn, cursor)
    pl.get_by_id(playlist_id)
    url_ids = pl.urls.split(',')

    print(url_ids)
    if url_id in url_ids:
        url_ids.remove(url_id)
        print('removing: %s' % url_id)
    print(url_ids)
    pl.urls = ",".join(url_ids)
    print(pl.urls)
    pl.save()

    return redirect("/playlists/info/%s" % playlist_id)

def flatten_urls(urls):
    u_ids = ""
    for u in urls:
        u_ids += "%s, " % u.id
    u_ids = u_ids.replace(" ", "")
    u_ids = u_ids[:-1]
    return u_ids



# End File: kio/kio-server/modules/controllers/playlists.py
