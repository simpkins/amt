#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#


class ImapError(Exception):
    def __init__(self, msg, *args):
        if args:
            self.msg = msg % args
        else:
            self.msg = msg

    def __str__(self):
        return self.msg


class ParseError(ImapError):
    def __init__(self, cmd_parts, msg=None, *args):
        self.cmd_parts = cmd_parts
        super().__init__(msg, *args)

    def __str__(self):
        return 'IMAP parse error: %s: %r' % (self.msg, self.cmd_parts)


class TimeoutError(ImapError):
    pass
