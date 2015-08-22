#!/usr/bin/python3 -tt
#
# Sample config for amt_ldap
#
# Copyright (c) 2015, Adam Simpkins
#
from amt.config import Account

account = Account(server='ldap.example.com',
                  user='DOMAIN\user',
                  protocol='ldaps')
base_dn = 'ou=ExampleOrg,dc=ExampleDomain,dc=com'
