"""Playlists Collection
Gets collections of play lists.

"""
from kio_server.collections.base import Base
from kio_server.models.playlist import Playlist


class Playlists(Base):

    def __init__(self, conn=None, cursor=None):
        super(Playlists, self).__init__(conn, cursor)
        self.table_name = Playlist().table_name
        self.collect_model = Playlist


# End File: kio/src/kio-server/collections/playlist.py
