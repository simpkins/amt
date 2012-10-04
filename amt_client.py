#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys

import amt.config
import amt.client
import amt.maildb.importer
from amt.maildb import MailDB, MaildirLocation, Location
from amt.maildir import Maildir


def create_tmp_maildb(maildir):
    '''
    Create a temporary MailDB, and import the messages from the specified
    maildir.
    '''
    class TmpProgressDisplay(amt.maildb.importer.ProgressDisplay):
        def want_percentage(self):
            return True

        def msg_import_done(self, loc, msg, num, total):
            sys.stdout.write('\r%d/%d %-60s' % (num, total, loc))
            sys.stdout.flush()

        def import_done(self, total):
            sys.stdout.write('\n')
            sys.stdout.flush()

    mdb = MailDB.temporary_db()
    importer = amt.maildb.importer.Importer(mdb, TmpProgressDisplay())
    importer.commit_every = 0

    try:
        importer.run(maildir)
    except KeyboardInterrupt:
        # On KeyboardInterrupt, just return whatever we imported so far.
        pass

    return mdb


def main():
    ap = argparse.ArgumentParser()
    mdb_arg = ap.add_mutually_exclusive_group()
    mdb_arg.add_argument('-m', '--maildb', metavar='PATH',
                         help='The path to the MailDB')
    mdb_arg.add_argument('-M', '--maildir', metavar='PATH',
                         help='The path to a maildir')
    ap.add_argument('-a', '--altscreen', action='store_true', default=False,
                    help='Use the terminal\'s alternate screen mode')
    args = ap.parse_args()

    if args.maildir:
        mdb = create_tmp_maildb(args.maildir)
    else:
        if not args.maildb:
            args.maildb = amt.config.default_maildb_path()
        mdb = MailDB.open_db(args.maildb)

    mua = amt.client.MUA(args, mdb)
    mua.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
