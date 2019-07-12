#!/usr/bin/python3 -tt
#
# Copyright (c) 2017, Adam Simpkins
#
'''
This script can be used to run tests for AMT configuration libraries.

Put tests in a test_data/ directory inside your normal AMT config directory.
Files in this directory should be named "*.mail", "*.tags", "or "*.url"

For each "*.mail" file, the test will parse it, perform classification,
and confirm that classification added the tags listed in the corresponding
"*.tags" file.  If a corresponding "*.url" file exists, the test harness will also check that guess_best_url() returns the URL listed in this file.
'''
import argparse
import logging
import os
import sys
import time
import traceback

import amt.config
import amt.message


class TestConfig:
    def __init__(self, config_dir, test_dir):
        self.config_dir = config_dir
        self.test_dir = test_dir

        modules = ['classify', 'urlview']
        self.amt_config = amt.config.load_config(config_dir, modules)


class TestData:
    def __init__(self, name):
        self.name = name
        self.mail_file = None
        self.tags = None
        self.best_url = None

    def set_data(self, data_type, path):
        if data_type == 'mail':
            self.mail_file = path
            return

        if data_type == 'tags':
            lines = self._readlines(path)
            self.tags = set(lines)
        elif data_type == 'url':
            lines = self._readlines(path)
            if len(lines) != 1:
                raise Exception('expected exactly one URL line in %r' % path)
            self.best_url = lines[0]
        else:
            raise Exception('unexpected file type for test %r: %r' %
                            (self.name, path))

    def _readlines(self, path):
        with open(path, 'r') as f:
            data = f.read()
        return data.splitlines()

    def check_complete(self):
        if self.mail_file is None:
            raise Exception('test %r has no mail file' % (self.name,))

        # We should have tags for all test messages
        if self.tags is None:
            raise Exception('test %r has no tags file' % (self.name,))


class TestRunner:
    def __init__(self, config, tests):
        self.config = config
        self.amt_config = config.amt_config
        self.tests = tests

        self.num_fail = 0
        self.num_success = 0

        if sys.stdout.isatty():
            self.color_red = '\033[1;31m'  # Bold and red
            self.color_green = '\033[1;32m'  # Bold and green
            self.color_reset = '\033[0m'
        else:
            self.color_red = ''
            self.color_green = ''
            self.color_reset = ''

    def run(self):
        start_time = time.time()

        for test in self.tests:
            try:
                with open(test.mail_file, 'rb') as f:
                    msg_data = f.read()

                msg = amt.message.Message.from_bytes(msg_data)
            except Exception as ex:
                self.add_failure_exc(test, 'parse_message')

            self.run_test(test, msg)

        end_time = time.time()

        print('-' * 40)
        if self.num_fail > 0:
            print('%s*** FAILURE ***%s' % (self.color_red, self.color_reset))
            print('Tests passed: %d' % self.num_success)
            print('Tests failed: %d' % self.num_fail)
            return_code = 1
        else:
            print('%sAll tests passed%s' % (self.color_green, self.color_reset))
            return_code = 0

        total_tests = self.num_success + self.num_fail
        total_time = end_time - start_time
        print('Ran %d tests in %.03f seconds' % (total_tests, total_time))
        return return_code

    def add_failure(self, test, name, detail):
        self.num_fail += 1
        print('%s.%s: %sFAIL%s' %
              (test.name, name, self.color_red, self.color_reset))
        for line in detail.splitlines():
            print('  ' + line)

    def add_failure_exc(self, test, name):
        detail = ''.join(traceback.format_exception(*sys.exc_info()))
        self.add_failure(test, name, detail)

    def add_success(self, test, name):
        self.num_success += 1
        print('%s.%s: %sSUCCESS%s' %
              (test.name, name, self.color_green, self.color_reset))

    def run_test(self, test, msg):
        self.test_classify(test, msg)
        self.test_url(test, msg)

    def test_classify(self, test, msg):
        classify_msg = self.amt_config.classify.classify_msg
        try:
            tags = classify_msg(msg)
        except Exception as ex:
            self.add_failure_exc(test, 'tags')
            return

        if tags != test.tags:
            detail = ('expected: %r\n'
                      'actual:   %r\n' %
                      (list(sorted(test.tags)), list(sorted(tags))))
            self.add_failure(test, 'tags', detail)
        else:
            self.add_success(test, 'tags')

    def test_url(self, test, msg):
        if test.best_url is None:
            return

        try:
            best_url = self.amt_config.urlview.guess_best_url(msg)
        except Exception as ex:
            self.add_failure_exc(test, 'url')
            return

        best_url_display = best_url.get_display_url(self.amt_config)
        if best_url_display != test.best_url:
            detail = ('expected: %s\nactual:   %s\n' %
                      (test.best_url, best_url_display))
            self.add_failure(test, 'url', detail)
        else:
            self.add_success(test, 'url')


def find_tests(config):
    data_dir = os.path.join(config.test_dir)
    tests = {}
    for entry in os.listdir(data_dir):
        if entry.startswith('.'):
            continue

        parts = entry.rsplit('.', 1)
        if len(parts) != 2:
            raise Exception('unexpected file in test data directory: %r' %
                            entry)
        name, data_type = parts
        test = tests.get(name)
        if test is None:
            test = TestData(name)
            tests[name] = test
        path = os.path.join(data_dir, entry)
        test.set_data(data_type, path)

    def get_test_name(test):
        return test.name

    tests = list(sorted(tests.values(), key=get_test_name))

    for test in tests:
        test.check_complete()

    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-c', '--config', metavar='CONFIG_DIR',
                    help='The path to the configuration directory')
    ap.add_argument('-t', '--test-dir',
                    help='The path to the test directory.')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.config is None:
        args.config = amt.config.expand_path('~/.amt')
    if args.test_dir is None:
        args.test_dir = os.path.join(args.config, 'test_data')

    config = TestConfig(args.config, args.test_dir)

    tests = find_tests(config)
    return TestRunner(config, tests).run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
