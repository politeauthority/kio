"""Playlist Model

"""
from .base_entity_meta import BaseEntityMeta


class Playlist(BaseEntityMeta):

    def __init__(self, conn=None, cursor=None):
        """Url init for a new device object, passing SQLite connection parameters."""
        super(Playlist, self).__init__(conn, cursor)
        self.table_name = 'playlists'

        self.field_map = [
            {
                'name': 'name',
                'type': 'str'
            }
        ]
        self.setup()

    def __repr__(self):
        """Playlist representation, show the name if we have one."""
        return "<Playlist: %s>" % self.name


# End File: kio/kio-server/modules/models/playlist.py
