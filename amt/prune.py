#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#
import datetime
import logging

from . import imap
from .imap import encode as imap_encode


class PruneConfig:
    def __init__(self, account, mailbox, prune_days):
        self.account = account
        self.mailbox = mailbox
        self.prune_days = prune_days


class _Pruner(object):
    def __init__(self, config):
        self.config = config
        self.uids = None

        delta = datetime.timedelta(days=config.prune_days)
        prune_date = datetime.datetime.now() - delta
        self.prune_date = prune_date

        self.retry_cout = 0
        self.retry_limit = 3

    def run(self):
        date_text = imap_encode.to_date(self.prune_date).decode('utf-8')
        logging.info(f'Pruning messages before {date_text} in '
                     f'{self.config.mailbox}')

        self.retry_count = 0
        while True:
            try:
                self.try_prune()
            except imap.TimeoutError:
                self.retry_count += 1
                if self.retry_count < self.retry_limit:
                    logging.info('IMAP Timeout.  Retrying...')
                    continue
                logging.error('Too many IMAP timeouts encountered')
                raise

    def try_prune(self):
        with imap.login(self.config.account, timeout=120) as conn:
            logging.debug(f'Opening mailbox {self.config.mailbox}...')
            conn.select_mailbox(self.config.mailbox)

            # Retry up to 3 times if we time out while finding
            # the messages to prune
            self.retry_count = 0
            self.retry_limit = 3

            # self.uids will already be set here if we are retrying after
            # an IMAP timeout.  We potentially could avoid performing the query
            # again here if self.uids is already set.  However if we timed out
            # on an EXPUNGE operation we can't really tell if the messages were
            # successfully deleted or not, so we aren't sure if we should try
            # to delete them again or if some or all of them no longer exist.
            # For now we simply always re-query the UID list just for
            # simplicity.
            self.uids = None
            if self.uids is None:
                logging.debug(f'Searching for messages to delete...')
                date_text = imap_encode.to_date(self.prune_date)
                self.uids = conn.uid_search(b'BEFORE', date_text)
                if not self.uids:
                    logging.info('No messages to prune '
                                 f'({conn.mailbox.num_messages} total)')
                    return
                logging.info(f'Will prune {len(self.uids)} of '
                             f'{conn.mailbox.num_messages} messages')

            self.retry_count = 0
            self.retry_limit = 3

            # MS Exchange seems to have some limit on how many messages can be
            # updated at once.  (It returns "BAD Command Error. 10" if a STORE
            # command has too many message IDs.)  Break down the requests into
            # smaller chunks of UIDs to avoid hitting this limit.
            chunk_size = 256
            while self.uids:
                now = self.uids[:chunk_size]
                remaining_uids = self.uids[chunk_size:]

                ranges = imap_encode.collapse_seq_ranges(now)
                logging.info(f'Deleting {ranges.decode("utf-8")}...')
                conn.uid_delete_msg(ranges)

                logging.debug('Expunging messages...')
                conn.expunge(timeout=300)

                self.uids = remaining_uids


def prune(config):
    '''Delete old messages from the specified mailbox.'''
    _Pruner(config).run()
