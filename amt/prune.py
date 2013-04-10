#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#
import datetime
import logging

from . import imap
from .imap import encode as imap_encode

from .imap.parse import _MONTHS_BY_NUM


class PruneConfig:
    def __init__(self, account, mailbox, prune_days):
        self.account = account
        self.mailbox = mailbox
        self.prune_days = prune_days


def prune(config):
    '''
    Delete old messages from the specified mailbox.
    '''
    delta = datetime.timedelta(days=config.prune_days)
    prune_date = datetime.datetime.now() - delta
    date_text = imap_encode.to_date(prune_date)
    logging.info('Pruning %s: messages before %s', config.mailbox, date_text)

    with imap.login(config.account, timeout=120) as conn:
        conn.select_mailbox(config.mailbox)

        uids = conn.uid_search(b'BEFORE', date_text)
        if not uids:
            logging.info('No messages to prune (%d total)',
                         conn.mailbox.num_messages)
            return

        logging.info('Pruning %d of %d messages',
                     len(uids), conn.mailbox.num_messages)

        # MS Exchange seems to have some limit on how many messages can be
        # updated at once.  (It returns "BAD Command Error. 10" if a STORE
        # command has too many message IDs.)  Break down the requests into
        # smaller chunks of UIDs to avoid hitting this limit.
        chunk_size = 256
        while uids:
            now = uids[:chunk_size]
            uids = uids[chunk_size:]

            ranges = imap_encode.collapse_seq_ranges(now)
            logging.info('Marking %s deleted', ranges)
            conn.uid_delete_msg(ranges)
        logging.info('Expunging messages...')
        conn.expunge()
