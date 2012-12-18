#!/usr/local/src/python/cpython/python -tt
#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import os
import sys

import amt.config
import amt.fetchmail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='CONFIG_DIR',
                        default='~/.amt',
                        help='The path to the configuration directory')
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG, format=log_format)
    else:
        logging.basicConfig(level=logging.INFO, format=log_format)

    # TODO: Add a lock file, to ensure that two fetchmail instances aren't
    # running at once.

    # TODO: Put a more generic mechanism in place for showing diagnostic output
    amt.fetchmail._log.setLevel(logging.DEBUG)

    amt_config = amt.config.load_config(args.config)
    scanner = amt_config.fetchmail.get_scanner()

    lock_path = os.path.join(amt_config.config_path, 'fetchmail.lock')
    with amt.config.LockFile(lock_path):
        scanner.account.prepare_password()
        scanner.run_forever()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
