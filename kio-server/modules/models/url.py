"""Url Model

"""
from .base import Base


class Url(Base):

    def __init__(self, conn=None, cursor=None):
        """Url init for a new device object, passing SQLite connection parameters."""
        super(Url, self).__init__(conn, cursor)
        self.table_name = 'urls'

        self.field_map = [
            {
                'name': 'name',
                'type': 'str'
            },
            {
                'name': 'address',
                'type': 'str'
            },
        ]
        self.setup()

    def __repr__(self):
        """Url representation, show the address if we have one."""
        return "<Url: %s>" % self.address


# End File: kio/kio-server/modules/models/url.py
