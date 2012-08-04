#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys

import amt.config
from amt.maildb import MailDB, MaildirLocation, Location
from amt.maildir import Maildir
from amt.message import Message


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-m', '--maildb', metavar='PATH',
                    help='The path to the MailDB')
    ap.add_argument('--commit-every', metavar='N', type=int,
                    default=20,
                    help='Commit DB changes after every Nth message.')
    ap.add_argument('maildir', metavar='MAILDIR',
                    help='The maildir to import')
    args = ap.parse_args()

    if not args.maildb:
        args.maildb = amt.config.default_maildb_path()

    if args.commit_every <= 0:
        arg.commit_every = 1

    mdb = MailDB.open_db(args.maildb)
    maildir = Maildir(args.maildir)

    for n, (key, path) in enumerate(maildir.list()):
        loc = MaildirLocation(path)
        print(loc)
        try:
            muid = mdb.get_muid_by_location(loc)
            # We've already imported this message
            print('  --> already imported')
            continue
        except KeyError:
            # This message doesn't exist.  Fall through and import it
            pass

        msg = Message.from_maildir(path)

        commit = ((n + 1) % args.commit_every == 0)

        muid, tuid = mdb.import_msg(msg, commit=False)
        mdb.add_location(muid, loc, commit=commit)

    mdb.commit()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
