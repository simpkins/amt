#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(sys.path[0]))
from amt import imap

from test_util import *


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

    def run(self):
        with self.test('create_conn'):
            self.conn = imap.Connection(self.args.server, self.args.port,
                                        ssl=False)

        with self.test('login'):
            self.conn.login(self.args.user, self.args.password)

        with self.test('select'):
            responses = self.conn.list_mailboxes(self.args.mailbox)
            if not responses:
                self.conn.create_mailbox(self.args.mailbox)
            self.conn.select_mailbox(self.args.mailbox)

        with self.test('append'):
            msg = random_message()
            self.conn.append_msg(self.args.mailbox, msg)

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
    ap.add_argument('-m', '--mailbox', default='amt_test',
                    help='The mailbox to use for testing')
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    TestSuite(args).run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
