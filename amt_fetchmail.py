#!/usr/local/src/python/cpython/python -tt
#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import sys

import amt.config
import amt.fetchmail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config_path', metavar='CONFIG_PATH',
                        help='The path to the configuration module')
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # TODO: Put a more generic mechanism in place for showing diagnostic output
    amt.fetchmail._log.setLevel(logging.DEBUG)

    config = amt.config.load_config(args.config_path)

    scanner = config.config_dict['fetchmail_scanner']
    scanner.account.prepare_password()
    scanner.run_forever()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
