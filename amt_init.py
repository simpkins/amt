#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys
import time

import amt.config
from amt.maildb import MailDB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-m', '--maildb', metavar='PATH',
                    help='The path where the new MailDB should be created')
    args = ap.parse_args()

    if not args.maildb:
        args.maildb = amt.config.default_maildb_path()

    print('Initializing maildb at %s...' % (args.maildb,))
    start = time.time()
    MailDB.create_db(args.maildb)
    end = time.time()
    print('Initialized maildb in %.2f seconds' % (end - start,))


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
