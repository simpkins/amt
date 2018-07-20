#!/usr/bin/python3 -tt
#
# Copyright (c) 2011, Adam Simpkins
#
import secretstorage


class PasswordError(Exception):
    pass


class NoPasswordError(PasswordError):
    def __init__(self):
        PasswordError.__init__(self, 'no matching password found')


def get_password(user=None, server=None, port=None, protocol=None):
    attributes = {}
    if user is not None:
        attributes['user'] = user
    if server is not None:
        attributes['server'] = server
    if port is not None:
        attributes['port'] = str(port)
    if protocol is not None:
        attributes['protocol'] = protocol

    dbus = secretstorage.dbus_init()
    collection = secretstorage.get_default_collection(dbus)
    items = list(collection.search_items(attributes))
    if not items:
        raise NoPasswordError()

    if len(items) > 1:
        raise PasswordError(
            "found multiple password entries matching the criteria"
        )

    secret = items[0].get_secret()
    return secret.decode('utf-8')
