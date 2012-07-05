#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import email.utils
import logging
import re

from amt.message import AddressList

from .tags import tags as mail_tags


class MailClassifier:
    def __init__(self):
        self.my_addresses = [
            'johndoe@example.com'
        ]

    def get_tags(self, msg):
        msg_classifier = MsgClassifier(self, msg)
        msg_classifier.run()
        return msg_classifier.tags


class MsgClassifier:
    def __init__(self, mail_classifier, msg):
        self.classifier = mail_classifier
        self.msg = msg
        self.look_for_mentions_me = True
        self.mentions_body = None

        self.tags = set()
        self._lower_body = None

    def lowercase_body(self):
        # Cache the lower-cased body text, since we may need it multiple times
        if self._lower_body is None:
            self._lower_body = self.msg.body_text.lower()
        return self._lower_body

    def add_tag(self, name, suffix=None):
        tag = mail_tags.get_tag(name, suffix)
        logging.debug('--> new tag: "%s"', tag.name)
        self.tags.add(tag)

    def run(self):
        self.process_by_destination()
        self.process_by_source()

        if self.look_for_mentions_me:
            # Add 'mentions-me' if my name is present in the message body
            if self.mentions_body is None:
                self.mentions_body = self.lowercase_body()

            if self.mentions_body.find('johndoe') >= 0:
                self.add_tag('mentions-me')

        self.process_meta_tags()

    def process_by_destination(self):
        """
        Add tags based on the message recipients.
        """
        # Add tags based on whether I'm listed in the To or Cc header
        self.process_to_cc()

        # Process the List-Id header
        list_ids = self.msg.get_all('List-Id', [])
        for list_id in list_ids:
            comment, addr = email.utils.parseaddr(list_id)
            self.add_tag('to-list-', addr)

    def process_to_cc(self):
        """
        Add 'to-me' or 'cc-me' if I am listed in the To or Cc header
        """
        for addr in self.classifier.my_addresses:
            if self.msg.to.contains(addr):
                self.add_tag('to-me')
                return

        for addr in self.classifier.my_addresses:
            if self.msg.cc.contains(addr):
                self.add_tag('cc-me')
                return

    def process_by_source(self):
        """
        Add tags based on the message source.

        This function contains all classifiers that add tags based on the
        message source.  Since there is generally only one message source,
        these classifiers are all mutually exclusive, and this function can
        return early as soon as one classifier matches.
        """
        pass

    def process_meta_tags(self):
        for tag in mail_tags.meta_tags:
            if tag.match(self.msg, self.tags):
                self.add_tag(tag)

    def ignore_mentions_after(self, text):
        if self.mentions_body is None:
            body = self.lowercase_body()
        else:
            body = self.mentions_body

        idx = body.find(text.lower())
        if idx >= 0:
            self.mentions_body = body[:idx]
