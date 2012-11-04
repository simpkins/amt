#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import datetime
import logging
import os
import queue
import random
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(sys.path[0]))
from amt import imap

from tests.lib import imap_server
from tests.lib.util import *


MAILBOX_PREFIX = 'amt_test'


class Test:
    def __init__(self, name, suite):
        self.name = name
        self.suite = suite

    def __enter__(self):
        self.suite.test_started(self.name)
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if exc_type is None:
            self.suite.test_success(self.name)
        else:
            self.suite.test_failure(self.name, exc_type, exc_value, exc_tb)


class TestSuite:
    def __init__(self, account):
        self.account = account
        self.num_success = 0
        self.num_failure = 0

        self.examine_thread = None
        self._stop = threading.Event()
        self.examine_events = queue.Queue()

    def clean(self):
        self.conn = imap.login(self.account)

        responses = self.conn.list_mailboxes(MAILBOX_PREFIX, '*')
        for response in responses:
            mbox_name = response.mailbox.decode('ASCII', errors='strict')
            print('Deleting mailbox "%s"' % mbox_name)
            self.conn.delete_mailbox(response.mailbox)

    def rand_mbox_name(self, length=8):
        choices = []
        choices.extend(chr(n) for n in range(ord('a'), ord('z') + 1))
        choices.extend(chr(n) for n in range(ord('A'), ord('Z') + 1))
        choices.extend(chr(n) for n in range(ord('0'), ord('9') + 1))

        rand_chars = []
        for n in range(length):
            idx = random.randrange(0, len(choices))
            rand_chars.append(choices[idx])
        return ''.join(rand_chars)

    def run(self):
        with self.test('login'):
            self.conn = imap.login(self.account)

        with self.test('create_mailbox'):
            # Get the mailbox delimiter
            responses = self.conn.list_mailboxes('', '')
            delim = responses[0].delimiter.decode('ASCII', errors='strict')

            for num_tries in range(5):
                suffix = self.rand_mbox_name()
                self.mbox_name = '%s%s%s' % (MAILBOX_PREFIX, delim, suffix)
                responses = self.conn.list_mailboxes('', self.mbox_name)
                if not responses:
                    break
            else:
                raise Exception('failed to pick unique mailbox name '
                                'after 5 tries')

            self.conn.create_mailbox(self.mbox_name)

        self._start_examine_thread()
        try:
            self.run_tests()
        finally:
            self._stop_examine_thread()
            with self.test('delete_mailbox'):
                self.conn.delete_mailbox(self.mbox_name)
            self.print_results()

    def run_tests(self):
        with self.test('select'):
            self.conn.select_mailbox(self.mbox_name)

        with self.test('append'):
            msg = random_message()
            self.conn.append_msg(self.mbox_name, msg)

            # The expect thread should see the new message
            response = self.expect_examine_event(b'EXISTS')
            self.assert_equal(response.number, 1)

        with self.test('search'):
            msg_nums = self.conn.search(b'ALL')
            self.assert_equal(msg_nums, [1])

        with self.test('fetch'):
            # Fetch the message, and make sure the contents are identical
            fetched_msg = self.conn.fetch_msg(1)

            self.assert_equal(fetched_msg.to, msg.to)
            self.assert_equal(fetched_msg.cc, msg.cc)
            self.assert_equal(fetched_msg.from_addr, msg.from_addr)
            self.assert_equal(fetched_msg.subject, msg.subject)
            self.assert_equal(int(fetched_msg.timestamp), int(msg.timestamp))
            delta = fetched_msg.datetime - msg.datetime
            self.assert_le(abs(delta), datetime.timedelta(seconds=1))
            self.assert_equal(fetched_msg.flags, msg.flags)
            self.assert_equal(fetched_msg.custom_flags, set([b'\\Recent']))
            self.assert_equal(fetched_msg.body_text, msg.body_text)
            self.assert_equal(fetched_msg.fingerprint(), msg.fingerprint())

        with self.test('delete'):
            msg_nums = self.conn.delete_msg(1, expunge_now=True)
            # The expect thread should see the expunge event
            response = self.expect_examine_event(b'EXPUNGE')
            self.assert_equal(response.number, 1)

    def assert_equal(self, value, expected):
        if value == expected:
            return
        raise AssertionError('assertion failed: %r != %r' % (value, expected))

    def assert_le(self, value, expected):
        if value <= expected:
            return
        raise AssertionError('assertion failed: %r > %r' % (value, expected))

    def examine_thread_main(self):
        conn2 = imap.login(self.account)
        conn2.select_mailbox(self.mbox_name, readonly=True)

        def response_handler(response):
            if self._stop.is_set():
                conn2.stop_idle()
            self.examine_events.put(response)

        self.examine_events.put(None)
        with conn2.untagged_handler(None, response_handler):
            while not self._stop.is_set():
                conn2.idle()

        conn2.close()
        self.examine_events.put(None)

    def expect_examine_event(self, resp_type, timeout=5):
        found = []
        try:
            while True:
                response = self.examine_events.get(timeout=timeout)
                if response.resp_type == resp_type:
                    return response
                found.append(response)
        except queue.Empty:
            pass
        raise AssertionError('expected examine thread to see a %s '
                             'response; found %s instead' %
                             (resp_type, found))

    def _start_examine_thread(self):
        self.examine_thread = threading.Thread(target=self.examine_thread_main)
        self.examine_thread.start()
        # Wait for the examine thread to start and select the mailbox
        event = self.examine_events.get(timeout=3)
        assert event is None

    def _stop_examine_thread(self):
        if self.examine_thread is None:
            return

        self._stop.set()

        # Add a new message to wake up the examine thread
        msg = random_message()
        self.conn.append_msg(self.mbox_name, msg)

        self.examine_thread.join()
        self.examine_thread = None

    def test(self, name):
        return Test(name, self)

    def test_started(self, name):
        pass

    def test_success(self, name):
        self.num_success += 1
        print('%s... success' % (name,))

    def test_failure(self, name, exc_type, exc_value, exc_tb):
        self.num_failure += 1
        print('%s... failure' % (name,))

    def print_results(self):
        total = self.num_success + self.num_failure
        print('-' * 60)
        print('Passed %d/%d tests' % (self.num_success, total))
        if self.num_success == total:
            print('Success!')
        else:
            print('*** FAILED ***')


class Tests(imap_server.ImapTests):
    def test(self):
        ts = TestSuite(self.server.get_account())
        ts.run()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-s', '--server',
                    help='The server to connect to for testing')
    ap.add_argument('-p', '--port', type=int,
                    help='The server port')
    ap.add_argument('-u', '--user',
                    help='The username for connecting to the server')
    ap.add_argument('-P', '--password',
                    help='The password for connecting to the server')
    ap.add_argument('-S', '--ssl', type=bool, metavar='Y/N', default=None,
                    help='Use SSL')
    ap.add_argument('--clean', action='store_true', default=False,
                    help='Clean test mailboxes from the server')
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    if args.server:
        if args.user is None or args.password is None:
            ap.error('--user and --password are both required when '
                     '--server is specified')
        account = imap.Account(server=args.server, port=args.port,
                               ssl=args.ssl, user=args.user,
                               password=args.password)

        ts = TestSuite(account)
        if args.clean:
            ts.clean()
        else:
            ts.run()
    else:
        if args.clean:
            ap.error('--clean can only be used with --server')

        with ImapServer() as server:
            ts = TestSuite(server.get_account())
            ts.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
