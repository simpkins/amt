#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from .err import ImapError, ParseError
from .cmd_splitter import CommandSplitter
from .parse import *


class ResponseStream:
    '''
    ResponseStream accepts raw IMAP response data via the feed() method,
    and invokes a callback with the parsed responses.
    '''
    def __init__(self, callback):
        self.splitter = CommandSplitter(self._on_cmd)
        self.callback = callback

    def feed(self, data):
        self.splitter.feed(data)

    def eof(self):
        self.splitter.eof()

    def _on_cmd(self, parts):
        resp = parse_response(parts)
        self.callback(resp)
