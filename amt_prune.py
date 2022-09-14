#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import os
import sys

import amt.config
import amt.prune


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

    amt_config = amt.config.load_config(args.config)

    lock_path = os.path.join(amt_config.config_path, 'prune.lock')
    with amt.config.LockFile(lock_path):
        for config in amt_config.prune.configs:
            config.account.prepare_auth()
        for config in amt_config.prune.configs:
            amt.prune.prune(config)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
