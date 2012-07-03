#!/usr/local/src/python/cpython/python -tt
#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import sys

import imap_util
import maildir
from message import Message
from getpassword import get_password


class Config:
    def __init__(self):
        self.port = imap_util.IMAP4_SSL_PORT
        self.password = None  # Must call prepare_password() to set

    def init(self):
        self.prepare_password()

    def init_post_imap(self, conn):
        pass

    def prepare_password(self):
        self.password = get_password(user=self.user, server=self.server,
                                     protocol='imaps')

    def should_process_msg(self, msg_uid):
        # TODO: Possibly store a DB of already seen UIDs, so we can
        # avoid re-downloading already processed messages without having to
        # delete them or move them out of the mailbox?
        return True

    def process_msg(self, msg, processor):
        pass


class ConfigInstantiation(Config):
    def __init__(self):
        super().__init__()
        self.server = 'imap.example.com'
        self.user = 'johndoe@example.com'
        self.mailbox = 'INBOX'
        self.backup_mailbox = 'INBOX/backup'
        self.dest_mailbox = '/home/johndoe/mail'

    def init(self):
        self.prepare_password()
        self.dest_maildir = maildir.Maildir(self.dest_mailbox, create=True)

    def process_msg(self, msg, processor):
        logging.debug('From: %s;  To: %s', msg.from_addr, msg.to)
        #processor.copy_to(self.backup_mailbox)
        #self.dest_maildir.add(msg)


class MessageProcessor:
    def __init__(self, msg, imap_conn, imap_uid):
        self.msg = msg
        self.imap_conn = imap_conn
        self.imap_uid = imap_uid

    def copy_to(self, mailbox):
        self.imap_conn.copy_msg(self.imap_uid, mailbox)

    def delete(self, expunge_now=False):
        self.imap_conn.delete_msg(self.imap_uid


class MailProcessor:
    def __init__(self, config):
        self.config = config
        self.config.init()

        self.conn = None

    def run(self):
        self.setup_conn()
        self.config.init_post_imap(self.conn)

        # TODO: Implement IMAP IDLE support and/or polling
        self.run_once()

    def setup_conn(self):
        self.conn = imap_util.Connection(self.config.server, self.config.port)
        self.conn.login(self.config.user, self.config.password)
        self.conn.select_mailbox(self.config.mailbox, readonly=True)

    def run_once(self):
        msg_ids = self.conn.search_msg_ids('ALL')
        logging.info('%d messages', len(msg_ids))

        for uid in msg_ids:
            if not self.config.should_process_msg(uid):
                continue

            parts = ['UID', 'FLAGS', 'INTERNALDATE', 'BODY.PEEK[]']
            msg = self.conn.fetch(uid, parts)
            if msg['UID'] != uid:  # Just for sanity
                raise Exception('unexpected UID: asked for %s, got %s' %
                                (uid, msg['UID']))

            msg = Message.from_imap(msg)
            processor = MessageProcessor(msg, self.conn, uid)
            self.config.process_msg(msg, processor)

            # Debugging: only process one message for now
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    config = ConfigInstantiation()

    processor = MailProcessor(config)
    processor.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
