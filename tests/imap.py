#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import os
import random
import sys

sys.path.insert(0, os.path.dirname(sys.path[0]))
from amt import imap

from test_util import *


MAILBOX_PREFIX = 'amt_test'


class Test:
    def __init__(self, name, suite):
        self.name = name
        self.suite = suite

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if exc_type is None:
            self.suite.success(self.name)
        else:
            self.suite.failure(self.name, exc_type, exc_value, exc_tb)


class TestSuite:
    def __init__(self, args):
        self.args = args
        self.num_success = 0
        self.num_failure = 0

    def login(self):
        self.conn = imap.Connection(self.args.server, self.args.port,
                                    ssl=False)
        self.conn.login(self.args.user, self.args.password)

    def clean(self):
        self.login()

        responses = self.conn.list_mailboxes(MAILBOX_PREFIX, '*')
        for response in responses:
            mbox_name = response.mailbox.decode('ASCII', errors='strict')
            print(mbox_name)
            self.conn.delete_mailbox(response.mailbox)

    def rand_mbox_name(self, length=8):
        choices = []
        choices.extend(chr(n) for n in range(ord('a'), ord('z') + 1))
        choices.extend(chr(n) for n in range(ord('A'), ord('Z') + 1))
        choices.extend(chr(n) for n in range(ord('0'), ord('9') + 1))

        rand_chars = []
        for n in range(length):
            idx = random.randint(0, len(choices))
            rand_chars.append(choices[idx])
        return ''.join(rand_chars)

    def run(self):
        with self.test('login'):
            self.login()

        with self.test('create_mailbox'):
            # Get the mailbox delimiter
            responses = self.conn.list_mailboxes('', '')
            delim = responses[0].delimiter.decode('ASCII', errors='strict')

            for num_tries in range(5):
                suffix = self.rand_mbox_name()
                mbox_name = '%s%s%s' % (MAILBOX_PREFIX, delim, suffix)
                responses = self.conn.list_mailboxes('', mbox_name)
                if not responses:
                    break
            else:
                raise Exception('failed to pick unique mailbox name '
                                'after 5 tries')

            self.conn.create_mailbox(mbox_name)

        try:
            self.run_tests(mbox_name)
        finally:
            with self.test('delete_mailbox'):
                self.conn.delete_mailbox(mbox_name)

    def run_tests(self, mbox_name):
        with self.test('select'):
            self.conn.select_mailbox(mbox_name)

        with self.test('append'):
            msg = random_message()
            self.conn.append_msg(mbox_name, msg)

        with self.test('search'):
            self.conn.search(b'ALL')

    def test(self, name):
        return Test(name, self)

    def success(self, name):
        self.num_success += 1
        print('%s... success' % (name,))

    def failure(self, name, exc_type, exc_value, exc_tb):
        self.num_failure += 1
        print('%s... failure' % (name,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-s', '--server', required=True,
                    help='The server to connect to for testing')
    ap.add_argument('-p', '--port', required=True,
                    type=int,
                    help='The server port')
    ap.add_argument('-u', '--user', required=True,
                    help='The username for connecting to the server')
    ap.add_argument('-P', '--password', required=True,
                    help='The password for connecting to the server')
    ap.add_argument('--clean', action='store_true', default=False,
                    help='Clean test mailboxes from the server')
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    ts = TestSuite(args)
    if args.clean:
        ts.clean()
    else:
        ts.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
