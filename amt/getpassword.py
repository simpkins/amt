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


# Main function just to help test the code above
if __name__ == '__main__':
    import argparse
    import os
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument('-u', '--user',
                    action='store',
                    help='The username')
    ap.add_argument('-s', '--server',
                    action='store',
                    help='The server')
    ap.add_argument('-p', '--port',
                    action='store', type=int,
                    help='The port number')
    ap.add_argument('-P', '--proto', '--protocol',
                    action='store', dest='protocol',
                    help='The port number')
    args = ap.parse_args()

    params = ('user', 'server', 'port', 'protocol')
    kwargs = {}
    for p in params:
        value = getattr(args, p)
        if value is not None:
            kwargs[p] = value

    try:
        pw = get_password(**kwargs)
    except NoPasswordError as ex:
        print("error: no matching password found", file=sys.stderr)
        sys.exit(os.EX_UNAVAILABLE)
    except PasswordError as ex:
        print(f"error: {ex}", file=sys.stderr)
        sys.exit(os.EX_DATAERR)

    print(pw)
    sys.exit(os.EX_OK)
