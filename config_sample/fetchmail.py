#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import amt.fetchmail
from amt import maildir

from .classifier import MailClassifier


class FetchmailConfig(amt.fetchmail.MailboxConfig):
    def __init__(self):
        super().__init__()
        self.server = 'imap.example.com'
        self.user = 'johndoe@example.com'
        self.mailbox = 'INBOX'
        self.backup_mailbox = 'INBOX/backup'
        self.dest_mailbox = '/home/johndoe/mail'

        self.classifier = MailClassifier()

    def init(self):
        self.prepare_password()
        self.dest_maildir = maildir.Maildir(self.dest_mailbox, create=True)

    def process_msg(self, msg, processor):
        logging.debug('From: %s;  To: %s', msg.from_addr, msg.to)

        # First copy the original unmodified message to the backup mailbox
        # on the server.
        processor.copy_to(self.backup_mailbox)

        # Next, compute the tags for the message
        tags = self.classifier.get_tags(msg)
        self.apply_tags(msg, tags)

        # Deliver the message to our local mailbox
        self.deliver_local(msg)

        # Delete the message from the server
        processor.delete_msg()

    def apply_tags(self, msg, tags):
        # Delete any existing X-Label header
        #
        # TODO: If the message headers already contain tags,
        # should we preserve tags not in the new set of tags?
        msg.remove_header('X-Label')
        msg.remove_header('X-Auto-Tags')

        # TODO: We should properly escape the tag.
        # email.utils doesn't seem to have any functions for this.
        # formataddr() doesn't do any escaping of the address.
        value = ' '.join('<%s>' % str(tag) for tag in tags)
        msg.add_header('X-Label', value)
        msg.add_header('X-Auto-Tags', value)

    def deliver_local(self, msg):
        # TODO: Update a local index (such as notmuch)
        self.dest_maildir.add(msg)
