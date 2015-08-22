#!/usr/bin/python3 -tt
#
# Sample config for amt_fetchmail
#
# Copyright (c) 2012, Adam Simpkins
#
import os
import logging
import sys
import traceback

from amt import fetchmail
from amt import maildir

from . import classify
from . import accounts


class MailProcessor(fetchmail.Processor):
    def __init__(self, root):
        super().__init__()
        self.scanner = None
        self.root = root
        self._created_mailboxes = set()

        inbox_path = os.path.join(self.root, 'INBOX')
        self.inbox = maildir.Maildir(inbox_path, create=True)

    def process_msg(self, msg):
        logging.info('processing message from %r: %r',
                     msg.from_addr, msg.subject)
        # Run our classification code on the message to generate
        # a set of tags for the message.
        try:
            tags = self.classify_msg(msg)
            logging.debug('tags: %r', tags)
        except Exception as ex:
            sys.stderr.write('error during classification: %s\n' % (ex,))
            traceback.print_exc()

        # If you wanted, you could send messages to different local folders
        # based on the classified tags.  This example just sends everything to
        # a local inbox folder.
        self.inbox.add(msg)
        return True

    def add_tag_headers(self, msg, tags):
        msg.remove_header('X-Label')
        msg.remove_header('X-Auto-Tags')

        # TODO: We should properly escape the tag.
        # email.utils doesn't seem to have any functions for this.
        # formataddr() doesn't do any escaping of the address.
        value = ' '.join('<%s>' % tag for tag in tags)
        msg.add_header('X-Label', value)
        msg.add_header('X-Auto-Tags', value)

    def classify_msg(self, msg):
        tags = classify.classify_msg(msg)
        self.add_tag_headers(msg, tags)

        if 'alert' in tags:
            dest = ('INBOX', 'alerts')
            self.copy_to(dest)
        elif 'hipri' in tags:
            dest = ('INBOX', 'hipri')
            self.copy_to(dest)

        return tags

    def copy_to(self, mailbox):
        '''
        Copy the message to another IMAP mailbox on the server.
        '''
        if mailbox not in self._created_mailboxes:
            self.scanner.conn.ensure_mailbox(mailbox)
            self._created_mailboxes.add(mailbox)
        self.scanner.copy_msg(mailbox)


def get_scanner():
    local_mail_dir = os.path.join(os.environ['HOME'], 'Mail')
    mail_processor = MailProcessor(local_mail_dir)

    mailbox = 'INBOX'
    backup_mailbox = ('INBOX', 'backup')
    scanner = fetchmail.FetchAndDeleteScanner(
        accounts.fb,
        mailbox,
        mail_processor,
        backup_mbox=backup_mailbox)

    mail_processor.scanner = scanner

    return scanner
