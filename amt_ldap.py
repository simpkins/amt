#!/usr/bin/python3 -tt
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

DEFAULT_ATTRS = [
    'cn',
    'userPrincipalName',
    'mail',
    'mailNickname',
    'displayName',
    'givenName',
    'sn',
    'uid',
]
MUTT_ATTRS = [
    # The following fields are used for display purposes
    'displayName',
    'mail',
    'title',
    # The following fields are used for sorting
    'uid',
    'mailNickname',
    'sn',
    'givenName',
]


def print_mutt_results(results):
    print('%d entries found' % (len(results,)))
    for entry in results:
        if (not getattr(entry, 'mail', None) or
                not getattr(entry, 'displayName', None)):
            continue
        if 'title' in entry and entry['title']:
            desc = entry['title'][0]
        else:
            desc = ''
        print('%s\t%s\t%s' % (entry['mail'][0], entry['displayName'][0], desc))


def print_results(results):
    for entry in results:
        print(entry.entry_dn)
        for key, values in sorted(entry.entry_attributes_as_dict.items()):
            for value in values:
                print('  %s: %s' % (key, value))


def _get_sort_name(entry):
    for attr_name in ('displayName', 'name'):
        try:
            attr = entry[attr_name]
            return str(attr)
        except KeyError:
            continue

    return entry.entry_dn


def _get_match_score(entry, lower_names):
    fields = [
        ('uid', 100),
        ('mailNickname', 90),
        ('sn', 80),
        ('givenName', 70),
    ]
    for field_name, field_score in fields:
        try:
            attr = entry[field_name]
        except KeyError:
            continue

        found = False
        for value in attr.values:
            if value.lower() in lower_names:
                return field_score

    return 0


def parse_filter(parser, args):
    if not args.user:
        if args.filter is None:
            parser.error('No users specified, and no --filter specified')
        return args.filter, _get_sort_name

    user_filter_string = ('(cn=*{0}*) (uid=*{0}*) '
                            '(proxyAddresses=*{0}*) (userPrincipalName=*{0}*)')
    user_filters = []
    if args.filter is not None:
        user_filters.append('({0})'.format(args.filter))
    for user in args.user:
        user_filters.append(user_filter_string.format(user))

    lower_names = set(user.lower() for user in args.user)

    def name_sort_key(entry):
        score = _get_match_score(entry, lower_names)
        sort_name = _get_sort_name(entry)
        # Negate the score so that high scores are shown first.
        # Sort by the sort_name when entries have equal scores.
        return (-score, sort_name)

    filter = '(|{0})'.format(' '.join(user_filters))
    return filter, name_sort_key


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
    ldap_filter, sort_key = parse_filter(parser, args)
    ldap_attrs = parse_attrs(parser, args, amt_config.ldap)

    account.prepare_auth()
    conn = amt.ldap.Connection(account=account)
    results = conn.search(base_dn=args.base_dn,
                          filter=ldap_filter,
                          attrs=ldap_attrs)
    results.sort(key=sort_key)

    if args.mutt:
        print_mutt_results(results)
    else:
        print_results(results)
    return 0


if __name__ == '__main__':
    sys.exit(main())
