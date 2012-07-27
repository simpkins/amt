#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#

from .classifier import MailClassifier
from .fetchmail import FetchmailConfig

from amt.config import Account

account = Account(server='imap.example.com',
                  user='johndoe',
                  protocol='imaps')
