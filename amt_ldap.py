#!/usr/bin/python -tt
#
# Copyright (c) 2013, Adam Simpkins
#
"""
Utility for performing LDAP searches.
"""

import argparse
import sys

import amt.config
import amt.ldap

DEFAULT_ATTRS = ['cn', 'userPrincipalName', 'mail', 'mailNickname',
                 'displayName', 'givenName', 'sn']
MUTT_ATTRS = ['displayName', 'mail', 'title']


def print_mutt_results(results):
    print('%d entries found' % (len(results,)))
    for (dn, entry) in results:
        if not entry['mail'] or not entry['displayName']:
            continue
        if entry.has_key('title') and entry['title']:
            desc = entry['title'][0]
        else:
            desc = ''
        print('%s\t%s\t%s' % (entry['mail'][0], entry['displayName'][0], desc))


def print_results(results):
    for (dn, entry) in results:
        print(dn)
        for key, value in entry.iteritems():
            print('  %s: %s' % (key, value))


def parse_filter(parser, args):
    if not args.user:
        if args.filter is None:
            parser.error('No users specified, and no --filter specified')
        return args.filter

    user_filter_string = ('(cn=*{0}*) (rdn=*{0}*) (uid=*{0}*) '
                            '(proxyAddresses=*{0}*) (userPrincipalName=*{0}*)')
    user_filters = []
    if args.filter is not None:
        user_filters.append('({0})'.format(args.filter))
    for user in args.user:
        user_filters.append(user_filter_string.format(user))

    return '(|{0})'.format(' '.join(user_filters))


def parse_attrs(parser, args, ldap_cfg):
    if args.mutt:
        if args.all_attrs:
            parser.error('cannot specify --all-attrs with --mutt')
        if args.attrs:
            parser.error('cannot specify --attrs with --mutt')
        return MUTT_ATTRS

    if args.all_attrs:
        if args.attrs:
            parser.error('cannot specify both --attrs and --all-attrs')
        return None
    if args.attrs:
        return args.attrs

    cfg_attrs = getattr(ldap_cfg, 'attrs', None)
    if cfg_attrs is not None:
        return cfg_attrs

    return DEFAULT_ATTRS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='CONFIG_DIR',
                        default='~/.amt',
                        help='The path to the configuration directory')
    parser.add_argument('-f', '--filter',
                        help='The filter to search for')
    parser.add_argument('--base-dn',
                        help='The base DN to use for searching')
    parser.add_argument('-a', '--attrs',
                        nargs='*',
                        help='The attributes to return from searches')
    parser.add_argument('-A', '--all-attrs',
                        action='store_true', default=False,
                        help='Return all attributes')
    parser.add_argument('-m', '--mutt',
                        action='store_true', default=False,
                        help='Output entries in a format suitable for mutt')
    parser.add_argument('user',
                        nargs='*',
                        help='User names to search for')
    args = parser.parse_args()

    amt_config = amt.config.load_config(args.config, ['ldap'])

    account = amt_config.ldap.account

    if args.base_dn is None:
        args.base_dn = amt_config.ldap.base_dn
    ldap_filter = parse_filter(parser, args)
    ldap_attrs = parse_attrs(parser, args, amt_config.ldap)

    account.prepare_password()
    conn = amt.ldap.Connection(account=account)
    results = conn.search(base_dn=args.base_dn,
                          filter=ldap_filter,
                          attrs=ldap_attrs)

    if args.mutt:
        print_mutt_results(results)
    else:
        print_results(results)
    return 0


if __name__ == '__main__':
    sys.exit(main())
