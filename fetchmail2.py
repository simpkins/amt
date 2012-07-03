#!/usr/local/src/python/cpython/python -tt
#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import sys

import amt.fetchmail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config_file', metavar='CONFIG_FILE',
                        help='The configuration file')
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    amt.fetchmail.run(args.config_file)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
