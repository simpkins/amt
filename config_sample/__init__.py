#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#

from .classifier import MailClassifier

from amt.config import Account

account = Account(server='imap.example.com',
                  user='johndoe',
                  protocol='imaps')


class FetchmailConfig(amt.fetchmail.MailboxConfig):
    def __init__(self):
        self.account = account
        self.mailbox = 'INBOX'
        self.classifier = MailClassifier()

        self.dest_mailbox = '/home/johndoe/mail'

    def init(self):
        self.account.prepare_password()
        self.dest_maildir = maildir.Maildir(self.dest_mailbox, create=True)
