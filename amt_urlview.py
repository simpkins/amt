#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#
import argparse
import bs4
import logging
import re
import sys
import urllib.parse

import amt.config
import amt.message
import amt.urlview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='CONFIG_DIR',
                        default='~/.amt',
                        help='The path to the configuration directory')
    parser.add_argument('-g', '--guess',
                        action='store_true', default=False,
                        help='Try to guess the preferred URL, and '
                        'automatically go to it')
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')

    args = parser.parse_args()

    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG, format=log_format)
    else:
        logging.basicConfig(level=logging.INFO, format=log_format)

    amt_config = amt.config.load_config(args.config, ['urlview'])

    mail_data = sys.stdin.buffer.read()
    msg = amt.message.Message.from_bytes(mail_data)

    if args.guess:
        amt.urlview.guess_best_url(amt_config, msg)
    else:
        urls = amt.urlview.extract_urls(amt_config, msg)
        amt.urlview.select_urls(amt_config, urls)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
