#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from .err import MailDBError
from . import interface


class Location(interface.Location):
    def __init__(self):
        self.mailbox = mailbox_loc

    @classmethod
    def deserialize(cls, data):
        if data.startswith(MaildirLocation.SERIALIZE_PREFIX):
            rest = data[len(MaildirLocation.SERIALIZE_PREFIX):]
            return MaildirLocation.deserialize_suffix(data)

        raise MailDBError('unknown serialized location format: %r', data)

    def serialize(self):
        raise NotImplementedError()


class MaildirLocation(Location):
    SERIALIZE_PREFIX = b'MAILDIR:'

    def __init__(self, path):
        self.path = path

    @classmethod
    def deserialize_suffix(cls, data):
        path = data.decode('utf-8', errors='surrogateescape')
        return MaildirLocation(path)

    def serialize(self):
        data = self.path.encode('utf-8', errors='surrogateescape')
        return b'MAILDIR: ' + data
