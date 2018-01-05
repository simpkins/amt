#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#

import ldap3
import ssl

from . import ssl_util


class Connection(object):
    def __init__(self, account):
        self.account = account

        # Don't allow non-secure connections for now; always require SSL/TLS
        if self.account.protocol != 'ldaps':
            raise Exception('Insecure LDAP not supported')

        ca_certs_file = list(ssl_util.find_ca_cert_files())[0]
        tls = ldap3.Tls(validate=ssl.CERT_REQUIRED,
                        version=ssl.PROTOCOL_TLSv1,
                        ca_certs_file=ca_certs_file)

        LDAPS_PORT = 636
        connect_timeout = 5.0
        self.server = ldap3.Server(self.account.server, port=LDAPS_PORT,
                                   use_ssl=True, tls=tls,
                                   connect_timeout=connect_timeout)
        self.setup_conn()

    def setup_conn(self):
        self.conn = ldap3.Connection(self.server, self.account.user,
                                     self.account.password)
        if not self.conn.bind():
            raise Exception(self.conn.last_error)

    def search(self, base_dn, filter, attrs=None, scope='SUBTREE'):
        if attrs is None:
            attrs = ldap3.ALL_ATTRIBUTES
        result = self.conn.search(base_dn, filter, scope, attributes=attrs)
        if not result:
            raise Exception(self.conn.last_error)
        return self.conn.entries
