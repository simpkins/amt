#!/usr/bin/python -tt
#
# Copyright (c) 2013, Adam Simpkins
#

# TODO: This code is still using python 2.x for now.
# I should eventually install python3-ldap to get LDAP support for python 3.
from __future__ import absolute_import

import ldap

from . import ssl_util


def _init():
    global _initialized
    if _initialized:
        return
    # Set up global LDAP options.
    for path in ssl_util.find_ca_cert_files():
        ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, path)
        break

    ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
    _initialized = True
_initialized = False


class Connection(object):
    def __init__(self, account):
        _init()
        self.account = account
        self.setup_conn()

    def setup_conn(self):
        uri_format = '{account.protocol}://{account.server}:{account.port}'
        uri = uri_format.format(account=self.account)
        self.conn = ldap.initialize(uri)
        if self.account is not None:
            self.conn.simple_bind_s(self.account.user, self.account.password)

    def search(self, base_dn, filter, attrs=None, scope=ldap.SCOPE_SUBTREE):
        return self.conn.search_s(base_dn, scope, filter, attrs)
