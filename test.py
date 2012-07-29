#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import os
import sys
import unittest


def load_test(loader, tests_dir, arg):
    parts = arg.split('.')
    if parts[0] == 'tests':
        parts = parts[1:]

    if not parts:
        tests = loader.discover(start_dir=tests_dir, pattern='*.py')
        return tests

    try:
        orig_path = sys.path
        sys.path.insert(0, tests_dir)
        return loader.loadTestsFromName('.'.join(parts))
    finally:
        sys.path = orig_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-b', '--buffer', type=bool, default=True,
                    help='Buffer output from each test, and only print them '
                    'if the test fails')
    ap.add_argument('tests', metavar='TEST', nargs='*',
                    help='The name of a test module or individual test case')
    args = ap.parse_args()

    top_dir = os.path.dirname(sys.argv[0])
    tests_dir = os.path.join(top_dir, 'tests')

    loader = unittest.loader.TestLoader()
    if not args.tests:
        test_suite = loader.discover(start_dir=tests_dir, pattern='*.py')
    else:
        tests = [load_test(loader, tests_dir, arg) for arg in args.tests]
        test_suite = unittest.suite.TestSuite(tests)

    verbosity = 2
    unittest.signals.installHandler()
    runner = unittest.runner.TextTestRunner(verbosity=verbosity,
                                            buffer=args.buffer)
    result = runner.run(test_suite)
    if result.wasSuccessful():
        return 0
    return 1


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
