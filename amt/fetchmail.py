#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging

from . import imap_util
from .getpassword import get_password
from .message import Message


class MailboxConfig:
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


class MessageProcessor:
    def __init__(self, msg, imap_conn, imap_uid):
        self.msg = msg
        self.imap_conn = imap_conn
        self.imap_uid = imap_uid

    def copy_to(self, mailbox):
        self.imap_conn.copy_msg(self.imap_uid, mailbox)

    def delete_msg(self, expunge_now=False):
        self.imap_conn.delete_msg(self.imap_uid, expunge_now=expunge_now)


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
        self.conn.select_mailbox(self.config.mailbox)

    def run_once(self):
        msg_ids = self.conn.search_msg_ids('NOT DELETED')
        logging.info('Fetching messages: mailbox has %d messages to consider',
                     len(msg_ids))

        num_processed = 0
        for uid in msg_ids:
            if not self.config.should_process_msg(uid):
                continue

            msg = self.conn.fetch_msg(uid)
            processor = MessageProcessor(msg, self.conn, uid)
            self.config.process_msg(msg, processor)
            num_processed += 1

        if num_processed > 0:
            logging.info('Processed %d messages; expunging mailbox',
                         num_processed)
            self.conn.expunge()
        else:
            logging.info('No messages to process')
