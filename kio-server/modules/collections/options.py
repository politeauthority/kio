"""Options Collection
Gets collections of options.

"""
import logging

from .base import Base
from ..models.option import Option


class Options(Base):

    def __init__(self, conn=None, cursor=None):
        super(Options, self).__init__(conn, cursor)
        self.table_name = Option().table_name
        self.collect_model = Option
        self.default_opts = []

    def set_defaults(self) -> bool:
        """Create Option values and set Option defaults where applicable. """
        print('Setting defaults')
        for opt in self.default_opts:
            if opt['name'] == 'console-password':
                continue

            logging.info('Option: %s' % opt['name'])
            option = Option(self.conn, self.cursor)
            option_made = option.set_default(opt)
            if option_made:
                logging.info('Created option: %s with value "%s"' % (option.name, option.value))
            else:
                logging.info('Not creating option: %s, already exists' % option.name)

        return True

# End File: lan-nanny/lan_nanny/modules/collections/options.py
