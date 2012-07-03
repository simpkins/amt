#!/usr/local/bin/python2.6 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import amt.fetchmail
from amt import maildir


class Config(amt.fetchmail.MailboxConfig):
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
        processor.copy_to(self.backup_mailbox)
        self.dest_maildir.add(msg)
        processor.delete_msg()


config = Config()
