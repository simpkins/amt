#!/usr/local/src/python/cpython/python -tt
#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import imaplib
import logging
import sys

import imap_util
import maildir
from message import Message
from getpassword import get_password


class Config:
    def __init__(self):
        self.server = 'imap.example.com'
        self.port = imaplib.IMAP4_SSL_PORT
        self.user = 'johndoe@example.com'
        self.password = None  # Must call prepare_password() to set
        self.mailbox = 'INBOX'

        self.dest_mailbox = '/home/johndoe/mail'

    def prepare_password(self):
        self.password = get_password(user=self.user, server=self.server)


class MailProcessor:
    def __init__(self, config):
        self.config = config
        self.dest_maildir = maildir.Maildir(config.dest_mailbox, create=True)

    def run(self):
        # TODO: Implement IMAP IDLE support and/or polling
        self.run_once()

    def run_once(self):
        conn = imap_util.Connection(self.config.server, self.config.port)
        conn.login(self.config.user, self.config.password)

        conn.select_mailbox(self.config.mailbox, readonly=True)
        msg_ids = conn.search_msg_ids('ALL')
        logging.info('%d messages', len(msg_ids))

        for uid in msg_ids:
            if self.should_skip_uid(uid):
                continue

            parts = ['UID', 'FLAGS', 'INTERNALDATE', 'BODY.PEEK[]']
            msg = conn.fetch_one(uid, parts)
            if msg['UID'] != uid:  # Just for sanity
                raise Exception('unexpected UID: asked for %s, got %s' %
                                (uid, msg['UID']))

            msg = Message.from_imap(msg)
            self.process_msg(msg)

            # Debugging: only process one message for now
            break

    def should_skip_uid(self, uid):
        # TODO: Possibly store a DB of already seen UIDs, so we can
        # avoid re-downloading already processed messages without having to
        # delete them or move them out of the mailbox?
        return False

    def process_msg(self, msg):
        logging.debug('From: %s;  To: %s', msg.from_addr, msg.to)
        self.dest_maildir.add(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    config = Config()
    config.prepare_password()

    processor = MailProcessor(config)
    processor.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
