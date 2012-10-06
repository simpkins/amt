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
        self.msgs = MsgList(self.mdb)

        with self.term.program_mode(altscreen=self.args.altscreen) as region:
            index_mode = IndexMode(region, self.mdb, self.msgs)
            try:
                index_mode.run()
            except QuitError:
                return
