"""Urls Collection
Gets collections of urls.

"""
from .base import Base
from ..models.url import Url


class Urls(Base):

    def __init__(self, conn=None, cursor=None):
        super(Urls, self).__init__(conn, cursor)
        self.table_name = Url().table_name
        self.collect_model = Url


# End File: kio/kio-server/modules/collections/urls.py
