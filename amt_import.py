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
    ap.add_argument('maildir', metavar='MAILDIR',
                    help='The maildir to import')
    args = ap.parse_args()

    if not args.maildb:
        args.maildb = amt.config.default_maildb_path()

    mdb = MailDB.open_db(args.maildb)
    maildir = Maildir(args.maildir)

    for key, path in maildir.list():
        loc = MaildirLocation(path)
        try:
            muid = mdb.get_muid_by_location(loc)
            # We've already imported this message
            continue
        except KeyError:
            # This message doesn't exist.  Fall through and import it
            pass

        print(loc)
        msg = Message.from_maildir(path)

        # TODO: Only commit every 10 messages or so
        commit = True
        mdb.import_msg(msg, commit=commit)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
