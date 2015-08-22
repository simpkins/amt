#!/usr/bin/python3 -tt
#
# Sample accounts configuration file.
# This isn't used directly by amt itself, but other configs import this.
#
# Copyright (c) 2015, Adam Simpkins
#
from amt.config import Account

example = Account(server='mail.example.com',
                  user='johndoe',
                  protocol='imaps')
default = example
