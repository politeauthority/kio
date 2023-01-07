"""Playlists Collection
Gets collections of play lists.

"""
from .base import Base
from ..models.playlist import Playlist


class Playlists(Base):

    def __init__(self, conn=None, cursor=None):
        super(Playlists, self).__init__(conn, cursor)
        self.table_name = Playlist().table_name
        self.collect_model = Playlist


# End File: kio/kio-server/modules/collections/playlist.py
