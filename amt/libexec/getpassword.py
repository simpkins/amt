#!/usr/bin/python3 -tt
#
# Copyright (c) 2018, Adam Simpkins
#
import argparse
import os
import secretstorage
import sys


def main():
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
    attributes = {}
    for p in params:
        value = getattr(args, p)
        if value is not None:
            attributes[p] = str(value)

    dbus = secretstorage.dbus_init()
    collection = secretstorage.get_default_collection(dbus)
    items = list(collection.search_items(attributes))
    if not items:
        print("error: no matching password found", file=sys.stderr)
        return os.EX_UNAVAILABLE
    if len(items) > 1:
        print(f"error: more than one matching entry found: "
              f"{len(items)} matches",
              file=sys.stderr)
        return os.EX_UNAVAILABLE

    password = items[0].get_secret()
    sys.stdout.buffer.write(password)
    sys.stdout.buffer.write(b"\n")
    return os.EX_OK


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
