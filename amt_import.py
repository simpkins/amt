#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys

import amt.config
import amt.maildb.importer
from amt.maildb import MailDB


def main():
    ap = argparse.ArgumentParser()
    mdb_arg = ap.add_mutually_exclusive_group()
    mdb_arg.add_argument('-m', '--maildb', metavar='PATH',
                         help='The path to the MailDB')
    mdb_arg.add_argument('--temporary-maildb',
                         action='store_true', default=False,
                         help='Import to a temporary MailDB '
                         '(only for testing purposes')
    ap.add_argument('--commit-every', metavar='N', type=int,
                    default=20,
                    help='Commit DB changes after every Nth message.')
    ap.add_argument('maildir', metavar='MAILDIR',
                    help='The maildir to import')
    args = ap.parse_args()

    if args.temporary_maildb:
        mdb = MailDB.temporary_db()
    else:
        if not args.maildb:
            args.maildb = amt.config.default_maildb_path()
        mdb = MailDB.open_db(args.maildb)

    progress = amt.maildb.importer.SimpleProgressDisplay()
    importer = amt.maildb.importer.Importer(mdb, progress)
    importer.commit_every = args.commit_every

    importer.run(args.maildir)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
