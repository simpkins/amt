#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys

import amt.config
from amt.maildb import MailDB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-m', '--maildb', metavar='PATH',
                    help='The path where the new MailDB should be created')
    args = ap.parse_args()

    if not args.maildb:
        args.maildb = amt.config.default_maildb_path()

    MailDB.create_db(args.maildb)
    print('Successfully initialized maildb at %s' % (args.maildb,))


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
