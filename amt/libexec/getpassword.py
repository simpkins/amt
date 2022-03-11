#!/usr/bin/python3 -tt
#
# Copyright (c) 2018, Adam Simpkins
#
import argparse
import os
import secretstorage
import sys
from typing import Optional


def create_label(
    user: Optional[str],
    server: Optional[str],
    port: Optional[int],
    protocol: Optional[str],
) -> str:
    label = ""
    if user is not None:
        label = f"{user}"
    if server is not None:
        label = f"{label} @ {server}"
    if port is not None:
        label = f"{label}:{port}"
    if protocol is not None:
        label = f"{label} ({protocol})"
    return label


def prompt_for_secret(label: str) -> bytes:
    import getpass
    return getpass.getpass(f"Password for {label}: ")


def main() -> int:
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
    ap.add_argument('--set',
                    action='store_true',
                    help='Set the password, instead of retrieving it')
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
        label = create_label(args.user, args.server, args.port, args.protocol)
        if args.set:
            secret = prompt_for_secret(label)
            collection.create_item(label, attributes, secret=secret)
            return os.EX_OK
        print(
            f"error: no matching password found for {label}", file=sys.stderr
        )
        return os.EX_UNAVAILABLE
    if len(items) > 1:
        print(f"error: more than one matching entry found: "
              f"{len(items)} matches",
              file=sys.stderr)
        return os.EX_UNAVAILABLE

    if args.set:
        label = create_label(args.user, args.server, args.port, args.protocol)
        secret = prompt_for_secret(label)
        items[0].set_secret(secret)
        return os.EX_OK

    password = items[0].get_secret()
    sys.stdout.buffer.write(password)
    sys.stdout.buffer.write(b"\n")
    return os.EX_OK


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
