#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import itertools

from amt import fetchmail
from amt import imap

from tests.lib import imap_server
from tests.lib.util import *


class RecordProcessor(fetchmail.Processor):
    def __init__(self):
        super(RecordProcessor, self).__init__()
        self.msgs = []

    def process_msg(self, msg):
        self.msgs.append(msg)
        return True


class Tests(imap_server.ImapTests):
    def get_conn(self):
        return imap.login(self.server.get_account())

    def create_mailbox(self, mailbox):
        with self.get_conn() as conn:
            conn.create_mailbox(mailbox)

    def add_msgs(self, mailbox, num):
        msgs = [random_message() for n in range(10)]
        with self.get_conn() as conn:
            for msg in msgs:
                conn.append_msg(mailbox, msg)
        return msgs

    def assert_msg_equal(self, msg1, msg2):
        # Compare fingerprints.  If they are equal, we are good.
        # If not, compare different parts of the message to give more
        # information about what is different
        if msg1.fingerprint() == msg2.fingerprint():
            return

        self.assertEqual(msg1.subject, msg2.subject)
        self.assertEqual(msg1.from_addr, msg2.from_addr)
        self.assertEqual(msg1.get_header('Message-ID'),
                         msg2.get_header('Message-ID'))
        self.assertEqual(msg1.body_text, msg2.body_text)

        for part1, part2 in itertools.zip_longest(msg1.iter_body_msgs(),
                                                  msg2.iter_body_msgs()):
            payload1 = part1.get_payload(decode=True)
            payload2 = part2.get_payload(decode=True)
            self.assertEqual(payload1, payload2)

        # We normally shouldn't reach here.  Something above should be
        # different if the fingerprints are different.  Compare the
        # fingerprints again just to ensure we fail when the fingerprints are
        # different.
        self.assertEqual(msg1.fingerprint(), msg2.fingerprint())

    def simple_scanner_test(self, mbox_name, scanner_class):
        self.create_mailbox(mbox_name)

        # Add 10 messages
        msgs = self.add_msgs(mbox_name, 10)

        # Fetch the messages, and make sure we get all of the messages
        processor = RecordProcessor()
        scanner = scanner_class(self.server.get_account(),
                                mbox_name, processor)
        scanner.run_once()
        self.assertEqual(len(msgs), len(processor.msgs))
        for orig, fetched in itertools.zip_longest(msgs, processor.msgs):
            self.assert_msg_equal(orig, fetched)

        # Add 10 more messages, and make sure we get them successfully
        more_msgs = self.add_msgs(mbox_name, 10)
        processor.msgs = []
        scanner.run_once()
        self.assertEqual(len(more_msgs), len(processor.msgs))
        for orig, fetched in itertools.zip_longest(more_msgs, processor.msgs):
            self.assert_msg_equal(orig, fetched)

        return msgs + more_msgs

    def test_fetch_all(self):
        mbox_name = 'test_fetch_all'
        msgs = self.simple_scanner_test(mbox_name, fetchmail.FetchAllScanner)

        # The FetchAllScanner leaves the messages in place.
        # Therefore if we create a new scanner it should still see all 20
        # messages.
        processor = RecordProcessor()
        scanner = fetchmail.FetchAllScanner(self.server.get_account(),
                                            mbox_name, processor)
        scanner.run_once()
        self.assertEqual(len(msgs), len(processor.msgs))
        for orig, fetched in itertools.zip_longest(msgs, processor.msgs):
            self.assert_msg_equal(orig, fetched)

    def test_fetch_and_delete(self):
        mbox_name = 'test_fetch_and_delete'
        self.simple_scanner_test(mbox_name, fetchmail.FetchAndDeleteScanner)

        # The FetchAndDeleteScanner deletes each message after it is processed.
        # Therefore the mailbox should no longer contain any messages.
        with self.get_conn() as conn:
            conn.select_mailbox(mbox_name)
            mbox_contents = conn.search(b'ALL')
        self.assertFalse(mbox_contents)

        # Make sure a new FetchAndDeleteScanner doesn't see any messages
        processor = RecordProcessor()
        scanner = fetchmail.FetchAndDeleteScanner(self.server.get_account(),
                                                  mbox_name, processor)
        scanner.run_once()
        self.assertFalse(processor.msgs)
