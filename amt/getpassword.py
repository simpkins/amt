#!/usr/bin/python3 -tt
#
# Copyright (c) 2011, Adam Simpkins
#
import secretstorage
from typing import Optional


class PasswordError(Exception):
    pass


class NoPasswordError(PasswordError):
    def __init__(self):
        PasswordError.__init__(self, 'no matching password found')


def get_password(
    user: str,
    server: str,
    port: Optional[int] = None,
    protocol: Optional[str] = None,
) -> str:
    attributes = {}
    attributes['user'] = user
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


def set_password(
    *,
    password: str,
    user: str,
    server: str,
    port: Optional[int] = None,
    protocol: Optional[str] = None,
) -> str:
    attributes = {}
    attributes['user'] = user
    attributes['server'] = server
    if port is not None:
        attributes['port'] = str(port)
    if protocol is not None:
        attributes['protocol'] = protocol

    secret = password.encode('utf-8')

    dbus = secretstorage.dbus_init()
    collection = secretstorage.get_default_collection(dbus)
    items = list(collection.search_items(attributes))
    if not items:
        label = f"Password for {user} @ {server}"
        if port is not None:
            label = f"{label}:{port}"
        if protocol is not None:
            label = f"{label} ({protocol})"

        item = collection.create_item(label, attributes, secret=secret)
    elif len(items) == 1:
        item = items[0]
        item.set_secret(secret)
    else:
        raise PasswordError(
            "found multiple password entries matching the criteria"
        )
