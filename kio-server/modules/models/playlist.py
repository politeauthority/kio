"""Playlist Model

"""
from .base_entity_meta import BaseEntityMeta
from .url import Url as UrlModel


class Playlist(BaseEntityMeta):

    def __init__(self, conn=None, cursor=None):
        """Url init for a new device object, passing SQLite connection parameters."""
        super(Playlist, self).__init__(conn, cursor)
        self.table_name = 'playlists'

        self.field_map = [
            {
                'name': 'name',
                'type': 'str'
            },
            {
                'name': 'urls',
                'type': 'str'
            }
        ]
        self.setup()

    def __repr__(self):
        """Playlist representation, show the name if we have one."""
        return "<Playlist: %s>" % self.name


    def get_urls(self):
        if not self.urls:
            return []
        url_ids = self.urls.split(',')
        urls = []
        for url_id in url_ids:
            u = UrlModel(self.conn, self.cursor)
            u.get_by_id(url_id)
            urls.append(u)
        return urls



# End File: kio/kio-server/modules/models/playlist.py
