#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from amt.term import Terminal

from .err import QuitError
from .index import IndexMode



class MUA:
    def __init__(self, args, mdb):
        self.args = args
        self.mdb = mdb
        self.term = Terminal()

    def run(self):
        with self.term.program_mode(altscreen=self.args.altscreen) as region:
            index_mode = IndexMode(region, self.mdb)
            try:
                index_mode.run()
            except QuitError:
                return
