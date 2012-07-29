#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from ..err import AMTError


class MailDBError(AMTError):
    pass


class BadIDError(MailDBError):
    def __init__(self, id_type, value, msg, *args):
        full_msg = 'invalid %s: "%s"' % (id_type, value)
        if msg:
            if args:
                msg = msg % args
            full_msg += ': ' + msg
        super().__init__(self, full_msg)
        self.value = value


class BadMUIDError(MailDBError):
    def __init__(self, value, msg, *args):
        super().__init__('MUID', value, msg, *args)


class BadTUIDError(MailDBError):
    def __init__(self, value, msg, *args):
        super().__init__('TUID', value, msg, *args)
