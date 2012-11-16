#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import datetime
import functools
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


class TmpMbox:
    def __init__(self, conn, prefix):
        self.conn = conn
        self.name = self._create_mbox(prefix)
        self.delete_on_exit = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        try:
            if self.delete_on_exit:
                self.delete()
        except Exception as ex:
            logging.warning('unable to delete temporary mailbox %s: %s',
                            self.name, ex)

    def delete(self):
        self.conn.delete_mailbox(self.name)
        self.delete_on_exit = False

    def _create_mbox(self, prefix):
        # Get the mailbox delimiter
        delim = self.conn.get_mailbox_delim()

        for num_tries in range(5):
            mbox_name = self.rand_mbox_name(prefix, delim)
            responses = self.conn.list_mailboxes('', mbox_name)
            if not responses:
                break
        else:
            raise Exception('failed to pick unique mailbox name '
                            'after 5 tries')

        self.conn.create_mailbox(mbox_name)
        return mbox_name

    def rand_mbox_name(self, prefix, delim, length=8):
        choices = []
        choices.extend(chr(n) for n in range(ord('a'), ord('z') + 1))
        choices.extend(chr(n) for n in range(ord('A'), ord('Z') + 1))
        choices.extend(chr(n) for n in range(ord('0'), ord('9') + 1))

        rand_chars = []
        for n in range(length):
            idx = random.randrange(0, len(choices))
            rand_chars.append(choices[idx])
        suffix = ''.join(rand_chars)
        return '%s%s%s' % (MAILBOX_PREFIX, delim, suffix)


class MboxExaminer:
    def __init__(self, account, mbox):
        self.account = account
        self.mbox = mbox
        self.events = queue.Queue()
        self._stop = threading.Event()
        self.thread = None
        self.conn = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.stop()

    def start(self):
        self.thread = threading.Thread(target=self._thread_main)
        self.thread.start()
        # Wait for the examine thread to start and select the mailbox
        event = self._get_event()
        assert event is None

    def stop(self):
        if self.thread is None:
            return

        # Set self._stop() and wake up the other thread if it is idling
        self._stop.set()
        if self.conn is not None:
            self.conn.stop_idle_threadsafe()

        self.thread.join()
        self.thread = None

    def expect_event(self, resp_type, number=None, timeout=5):
        found = []
        try:
            while True:
                response = self._get_event()
                if response.resp_type == resp_type:
                    if number is not None and number != response.number:
                        raise AssertionError('expected %s response with '
                                             'number %d, got %d' %
                                             (resp_type, number,
                                                 response.number))
                    return response
                found.append(str(response))
        except queue.Empty:
            pass
        raise AssertionError('expected examine thread to see a %s '
                             'response; found %s instead' %
                             (resp_type, found))

    def _get_event(self):
        event = self.events.get(timeout=3)
        if isinstance(event, Exception):
            raise event
        return event

    def _thread_main(self):
        try:
            with imap.login(self.account) as self.conn:
                self.conn.select_mailbox(self.mbox, readonly=True)

                # Add an event to let the the main thread know we have started
                # successfully.
                self.events.put(None)

                self._main_loop()
        except Exception as ex:
            self.events.put(ex)
        self.conn = None

    def _main_loop(self):
        def response_handler(response):
            if self._stop.is_set():
                self.conn.stop_idle()
            self.events.put(response)

        with self.conn.untagged_handler(None, response_handler):
            while not self._stop.is_set():
                self.conn.idle()


def conn_test(fn):
    @functools.wraps(fn)
    def test_wrapper(self):
        with imap.login(self.account) as conn:
                fn(self, conn)
    return test_wrapper


def mbox_test(fn):
    @functools.wraps(fn)
    def test_wrapper(self):
        with imap.login(self.account) as conn:
            with self.tmp_mbox(conn) as mbox:
                conn.select_mailbox(mbox.name)
                fn(self, conn, mbox.name)
    return test_wrapper


def examine_mbox_test(fn):
    @functools.wraps(fn)
    def test_wrapper(self):
        with imap.login(self.account) as conn:
            with self.tmp_mbox(conn) as mbox:
                with self.examiner(mbox) as examiner:
                    conn.select_mailbox(mbox.name)
                    fn(self, conn, mbox.name, examiner)
    return test_wrapper


class Tests(imap_server.ImapTests):
    @classmethod
    def set_account(cls):
        cls.account = account

    @classmethod
    def setUpClass(cls):
        cls.server = None
        if hasattr(cls, 'account') and cls.account is not None:
            return

        try:
            cls.server = imap_server.ImapServer()
            cls.server.start()
            cls.account = cls.server.get_account()
        except imap_server.NoImapServerError as ex:
            # Just set cls.no_server_msg for now,
            # and let setUp() skip each individual test.  This makes the
            # test reporting nicer than if we just raised SkipTest here.
            cls.server = None
            cls.no_server_msg = str(ex)

    @classmethod
    def tearDownClass(cls):
        if cls.account is not None:
            cls.clean_tmp_mailboxes(cls.account)
        if cls.server is not None:
            cls.server.stop()
            cls.server = None
            cls.account = None

    def setUp(self):
        if self.account is None:
            raise unittest.SkipTest(self.no_server_msg)
        super().setUp()

    def test_login(self):
        conn = imap.login(self.account)
        conn.close()

    @conn_test
    def test_create_mailbox(self, conn):
        mbox = self.tmp_mbox(conn)
        mbox.delete()

    @examine_mbox_test
    def test_append(self, conn, mbox, examiner):
        msg = random_message()
        conn.append_msg(mbox, msg)

        # The expect thread should see the new message
        response = examiner.expect_event(b'EXISTS', 1)

    @mbox_test
    def test_search(self, conn, mbox):
        msgs = [
            random_message(from_addr=('Alice', 'user1@example.com')),
            random_message(from_addr=('Bob', 'user2@example.com')),
            random_message(from_addr=('Carl', 'user3@example.com')),
            random_message(from_addr=('Alice', 'user1@example.com')),
            random_message(from_addr=('Dave', 'user4@example.com')),
        ]
        for msg in msgs:
            conn.append_msg(mbox, msg)

        # Test searching for all messages
        msg_nums = conn.search(b'ALL')
        expected_nums = list(range(1, len(msgs) + 1))
        self.assert_equal(msg_nums, expected_nums)

        # Search for messages from user2
        msg_nums = conn.search(b'FROM user2')
        expected_nums = [2]
        self.assert_equal(msg_nums, expected_nums)

        # Search for messages from user1
        msg_nums = conn.search(b'FROM Alice')
        expected_nums = [1, 4]
        self.assert_equal(msg_nums, expected_nums)

    @mbox_test
    def test_fetch(self, conn, mbox):
        # Add a message
        msg = random_message()
        conn.append_msg(mbox, msg)

        # Fetch the message, and make sure the contents are identical
        fetched_msg = conn.fetch_msg(1)
        self.assert_msg_equal(fetched_msg, msg)

    @examine_mbox_test
    def test_delete(self, conn, mbox, examiner):
        # Add 2 messages
        msg = random_message()
        conn.append_msg(mbox, msg)
        response = examiner.expect_event(b'EXISTS', 1)

        msg = random_message()
        conn.append_msg(mbox, msg)
        response = examiner.expect_event(b'EXISTS', 2)

        found_msgs = conn.search(b'ALL')
        self.assert_equal(found_msgs, [1, 2])

        # Delete the first message
        msg_nums = conn.delete_msg(1, expunge_now=False)
        # We should still be able to see the first message,
        # given that we haven't expunged yet.
        found_msgs = conn.search(b'ALL')
        self.assert_equal(found_msgs, [1, 2])
        found_msgs = conn.search(b'DELETED')
        self.assert_equal(found_msgs, [1])
        found_msgs = conn.search(b'NOT DELETED')
        self.assert_equal(found_msgs, [2])

        conn.expunge()
        # The expect thread should see the expunge event
        response = examiner.expect_event(b'EXPUNGE', 1)

        found_msgs = conn.search(b'ALL')
        self.assert_equal(found_msgs, [1])
        found_msgs = conn.search(b'DELETED')
        self.assert_equal(found_msgs, [])
        found_msgs = conn.search(b'NOT DELETED')
        self.assert_equal(found_msgs, [1])

        msg_nums = conn.delete_msg(1, expunge_now=True)
        response = examiner.expect_event(b'EXPUNGE', 1)
        found_msgs = conn.search(b'ALL')
        self.assert_equal(found_msgs, [])

    @examine_mbox_test
    def test_copy(self, dest_conn, dest_mbox, examiner):
        with imap.login(self.account) as src_conn:
            with self.tmp_mbox(src_conn) as src_mbox:
                src_conn.select_mailbox(src_mbox.name)
                msg = random_message()
                src_conn.append_msg(src_mbox.name, msg)
                src_conn.copy(1, dest_mbox)

                response = examiner.expect_event(b'EXISTS', 1)
                # Fetch the message from the dest mailbox,
                # and make sure it is the same as the source message.
                # We have to at least send a noop on the dest conn
                # so that it sees an EXISTS response for the new message
                # before it can fetch it.  Use wait_for_exists() to do this.
                dest_conn.wait_for_exists(timeout=1)
                fetched_msg = dest_conn.fetch_msg(1)
                self.assert_msg_equal(fetched_msg, msg)

    def tmp_mbox(self, conn):
        return TmpMbox(conn, MAILBOX_PREFIX)

    def examiner(self, mbox):
        if isinstance(mbox, TmpMbox):
            mbox = mbox.name
        return MboxExaminer(self.account, mbox)

    @classmethod
    def clean_tmp_mailboxes(cls, account):
        with imap.login(account) as conn:
            responses = conn.list_mailboxes(MAILBOX_PREFIX, '*')
            for response in responses:
                mbox_name = response.mailbox.decode('ASCII', errors='strict')
                print('Deleting mailbox "%s"' % mbox_name)
                conn.delete_mailbox(response.mailbox)

    def assert_equal(self, a, b):
        self.assertEqual(a, b)

    def assert_le(self, a, b):
        self.assertLessEqual(a, b)

    def assert_msg_equal(self, msg1, msg2):
        self.assert_equal(msg1.to, msg2.to)
        self.assert_equal(msg1.cc, msg2.cc)
        self.assert_equal(msg1.from_addr, msg2.from_addr)
        self.assert_equal(msg1.subject, msg2.subject)
        self.assert_equal(int(msg1.timestamp),
                          int(msg2.timestamp))
        delta = msg1.datetime - msg2.datetime
        self.assert_le(abs(delta), datetime.timedelta(seconds=1))
        self.assert_equal(msg1.flags, msg2.flags)
        self.assert_equal(msg1.custom_flags, set([b'\\Recent']))
        self.assert_equal(msg1.body_text, msg2.body_text)
        self.assert_equal(msg1.fingerprint(), msg2.fingerprint())


class TestSuite:
    def run_tests(self):
        with self.test('delete'):
            msg_nums = self.conn.delete_msg(1, expunge_now=True)
            # The expect thread should see the expunge event
            response = self.expect_examine_event(b'EXPUNGE')
            self.assert_equal(response.number, 1)


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
    ap.add_argument('-v', '--verbose',
                    action='count', default=0,
                    help='Increase the verbosity')
    ap.add_argument('--clean', action='store_true', default=False,
                    help='Clean test mailboxes from the server')
    ap.add_argument('tests', nargs='*',
                    help='Individual tests names to run')
    args = ap.parse_args()

    if args.verbose > 0:
        logging.basicConfig(level=logging.DEBUG)

    account = None
    if args.server:
        if args.user is None or args.password is None:
            ap.error('--user and --password are both required when '
                     '--server is specified')
        account = imap.Account(server=args.server, port=args.port,
                               ssl=args.ssl, user=args.user,
                               password=args.password)
        Tests.set_account(account)

    if args.clean:
        if not account:
            ap.error('--clean specified without --server')
        Tests.clean_tmp_mailboxes(account)
        return 0

    loader = unittest.loader.TestLoader()
    if args.tests:
        module = sys.modules['__main__']
        test_suite = loader.loadTestsFromNames(args.tests, module)
    else:
        test_suite = loader.loadTestsFromTestCase(Tests)

    verbosity = 2
    unittest.signals.installHandler()
    runner = unittest.runner.TextTestRunner(verbosity=verbosity, buffer=False)
    result = runner.run(test_suite)
    if result.wasSuccessful():
        return 0
    return 1


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
