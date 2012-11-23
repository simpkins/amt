#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import logging
import os
import sys

import amt.config
import amt.message


def load_message(path):
    if path == '-':
        msg_data = sys.stdin.buffer.read()
        return amt.message.Message.from_bytes(msg_data)

    # Just use from_maildir().
    # This will parse maildir flags from the filename if they are present,
    # but will still do the right thing even if the filename isn't a
    # maildir-style name.
    return amt.message.Message.from_maildir(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='CONFIG_DIR',
                        default='~/.amt',
                        help='The path to the configuration directory')
    parser.add_argument('-v', '--verbose', dest='verbose', action='count',
                        default=1, help='Increase the verbosity')
    parser.add_argument('msg_path', metavar='MSG_PATH',
                         help='The path to a message to classify, or "-" to '
                         'read from stdin')

    args = parser.parse_args()

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    amt_config = amt.config.load_config(args.config)
    classify_msg = amt_config.classify.classify_msg

    msg = load_message(args.msg_path)
    tags = classify_msg(msg)
    for tag in tags:
        print(tag)


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
