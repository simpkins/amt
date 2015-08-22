#!/usr/bin/python3 -tt
#
# Sample config file for amt_prune.
#
# Copyright (c) 2015, Adam Simpkins
#
from amt.prune import PruneConfig as PC

from . import accounts

# Which mailboxes to prune.
# Messages older than prune_days will be deleted.
configs = [
    PC(accounts.example, ('INBOX', 'alerts'), prune_days=7),
    PC(accounts.example, ('INBOX', 'backup'), prune_days=14),
    PC(accounts.example, ('INBOX', 'hipri'), prune_days=35),
]
