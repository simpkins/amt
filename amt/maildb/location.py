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
            return MaildirLocation.deserialize_suffix(rest)

        raise MailDBError('unknown serialized location format: %r', data)

    def serialize(self):
        raise NotImplementedError()


# TODO: We should probably have the Mailbox location be broken out separately.
# TODO: We should support relative locations, where the MailDB contians a root
# path, and the Mailbox is relative to the MailDB root.
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
        return self.SERIALIZE_PREFIX + data

    def __str__(self):
        return self.path

    def __repr__(self):
        return 'MaildirLocation(%r)' % (self.path,)

    def __eq__(self, other):
        if not isinstance(other, MaildirLocation):
            return False
        return self.path == other.path

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.path)
