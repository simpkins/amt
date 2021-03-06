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
                return
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

            # Only delete up to 256 messages at once.
            #
            # Older versions of MS Exchange would explicitly fail requests with
            # too many messages at once.  It would return
            # "BAD Command Error. 10" if a STORE command has too many message
            # IDs.
            #
            # Newer versions of MS Exchange running on office365.com simply
            # close or reset the connection on receipt of STORE requests with
            # large numbers of message IDs.
            chunk_size = 256

            idx = 0
            total_count = len(self.uids)
            while self.uids:
                if chunk_size is not None:
                    now = self.uids[:chunk_size]
                    remaining_uids = self.uids[chunk_size:]
                else:
                    now = self.uids
                    remaining_uids = []

                idx += len(now)
                ranges = imap_encode.collapse_seq_ranges(now)
                logging.info(
                    f'[{idx}/{total_count}] '
                    f'Deleting {ranges.decode("utf-8")}...'
                )
                conn.uid_delete_msg(ranges, timeout=600)
                self.uids = remaining_uids

            conn.close_mailbox(timeout=900)


def prune(config):
    '''Delete old messages from the specified mailbox.'''
    _Pruner(config).run()
