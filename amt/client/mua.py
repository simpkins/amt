#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from amt.term import Terminal

from .err import QuitError
from .index import IndexMode
from .msg import IndexMsg, MsgList


class MUA:
    def __init__(self, args, mdb):
        self.args = args
        self.mdb = mdb
        self.term = Terminal()

    def run(self):
        cursor = self.mdb.db.execute(
                'SELECT muid, tuid, subject, from_name, from_addr, timestamp '
                'FROM messages '
                'ORDER BY tuid')
        self.msgs = MsgList([IndexMsg(self.mdb, *items) for items in cursor])

        with self.term.program_mode(altscreen=self.args.altscreen) as region:
            index_mode = IndexMode(region, self.mdb, self.msgs)
            try:
                index_mode.run()
            except QuitError:
                return
