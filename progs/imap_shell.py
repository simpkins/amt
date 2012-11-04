#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import cmd
import functools
import readline
import shlex
import string
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(sys.path[0]))
import amt.config
from amt import imap


class ArgumentExit(Exception):
    def __init__(self, status, msg):
        super(ArgumentExit, self).__init__(msg)
        self.status = status
        self.msg = msg


class BoundWrapper:
    def __init__(self, wrapper, instance):
        self.wrapper = wrapper
        self.instance = instance

    def __call__(self, line):
        tokens = shlex.split(line)
        try:
            args = self.wrapper.parse_args(tokens)
        except ArgumentExit as ex:
            if ex.msg:
                print('error: ' + ex.msg)
            return

        try:
            return self.wrapper.fn(self.instance, **vars(args))
        except Exception as ex:
            traceback.print_exc()
            return


class Wrapper:
    def __init__(self, fn):
        self.fn = fn
        functools.update_wrapper(self, self.fn)

        name = fn.__name__
        if name.startswith('do_'):
            name = name[3:]
        self.ap = argparse.ArgumentParser(prog=name)
        self.ap.exit = self.handle_exit

    def add_argument(self, *args, **kwargs):
        return self.ap.add_argument(*args, **kwargs)

    def parse_args(self, args):
        return self.ap.parse_args(args)

    def __get__(self, instance, owner):
        return BoundWrapper(self, instance)

    def handle_exit(self, status=0, msg=None):
        raise ArgumentExit(status, msg)


def cmd_fn(fn):
    return Wrapper(fn)


class ImapShell(cmd.Cmd):
    def __init__(self, account):
        super(ImapShell, self).__init__()
        self.account = account

    def run(self):
        if self.account.protocol == 'imap':
            ssl = False
        elif self.account.protocol == 'imaps':
            ssl = True
        else:
            raise Exception('unsupported account protocol: %r' %
                            (self.account.protocol,))

        print('Connecting to %s:%d' % (self.account.server, self.account.port))
        self.conn = imap.Connection(self.account.server, self.account.port,
                                    ssl=ssl)
        print('Logging in as %s' % (self.account.user,))
        self.conn.login(self.account.user, self.account.password)
        print('Logged in.')
        caps = (cap.decode('utf-8', errors='replace') for cap in
                self.conn.get_capabilities())
        print('Server capabilities: %s' % ' '.join(caps))

        self.update_prompt()
        self.cmdloop()

    def update_prompt(self):
        prompt = self.account.server
        if self.conn.mailbox is not None:
            prompt += ':' + self.conn.mailbox.name
            if self.conn.mailbox.state == imap.STATE_READ_ONLY:
                prompt += ' (read-only)'

        self.prompt = prompt + '> '

    @cmd_fn
    def do_list(self, reference=None, mailbox=None):
        if reference is None:
            reference = ''
        if mailbox is None:
            mailbox = '*'

        fmt = '{mailbox:<20} {delim:<5} {attributes}'
        responses = self.conn.list_mailboxes(reference, mailbox)
        print(fmt.format(mailbox='Mailbox', delim='Delim',
                         attributes='Attributes'))
        for response in responses:
            mbox = self.fmt_str(response.mailbox)
            delim = self.fmt_str(response.delimiter)
            attrs = self.fmt_list(response.attributes)
            print(fmt.format(mailbox=mbox, delim=delim, attributes=attrs))

    do_list.add_argument('reference', nargs='?')
    do_list.add_argument('mailbox', nargs='?')
    do_ls = do_list

    @cmd_fn
    def do_select(self, mailbox, readonly=False):
        self.conn.select_mailbox(mailbox)
        self.update_prompt()

    do_select.add_argument('mailbox')
    do_select.add_argument('-r', '--readonly',
                           action='store_true', default=False)

    @cmd_fn
    def do_examine(self, mailbox):
        self.conn.select_mailbox(mailbox, readonly=True)
        self.update_prompt()

    do_examine.add_argument('mailbox')

    @cmd_fn
    def do_close(self):
        self.conn.close_mailbox()
        self.update_prompt()

    def do_EOF(self, arg):
        print()
        return True

    @cmd_fn
    def do_search(self, criteria, uid=False):
        if not criteria:
            criteria = [b'ALL']
        else:
            criteria = [c.encode('ASCII', errors='strict') for c in criteria]

        if uid:
            msg_nums = self.conn.uid_search(*criteria)
        else:
            msg_nums = self.conn.search(*criteria)
        print(self.fmt_list(msg_nums))

    do_search.add_argument('criteria', nargs='*')
    do_search.add_argument('-u', '--uid', action='store_true', default=False)

    @cmd_fn
    def do_fetch(self, msg_nums, attributes, uid=False):
        if not attributes:
            attributes = ['ENVELOPE']
        if uid:
            resp = self.conn.uid_fetch(msg_nums, attributes)
        else:
            resp = self.conn.fetch(msg_nums, attributes)
        print(resp)

    do_fetch.add_argument('msg_nums', type=int, nargs='+')
    do_fetch.add_argument('-a', '--attributes', action='append')
    do_fetch.add_argument('-u', '--uid', action='store_true', default=False)

    @cmd_fn
    def do_add_flag(self, msg_num, flags, uid):
        if uid:
            self.conn.uid_add_flags([msg_num], flags)
        else:
            self.conn.add_flags([msg_num], flags)

    do_add_flag.add_argument('msg_num', type=int)
    do_add_flag.add_argument('flags', nargs='+')
    do_add_flag.add_argument('-u', '--uid', action='store_true', default=False)

    @cmd_fn
    def do_rm_flag(self, msg_num, flags, uid):
        if uid:
            self.conn.uid_remove_flags([msg_num], flags)
        else:
            self.conn.remove_flags([msg_num], flags)

    do_rm_flag.add_argument('msg_num', type=int)
    do_rm_flag.add_argument('flags', nargs='+')
    do_rm_flag.add_argument('-u', '--uid', action='store_true', default=False)

    @cmd_fn
    def do_delete(self, msg_num, uid, expunge):
        if uid:
            self.conn.uid_delete_msg([msg_num], expunge_now=expunge)
        else:
            self.conn.delete_msg([msg_num], expunge_now=expunge)

    do_delete.add_argument('msg_num', type=int)
    do_delete.add_argument('-e', '--expunge', action='store_true',
                           default=False)
    do_delete.add_argument('-u', '--uid', action='store_true', default=False)

    @cmd_fn
    def do_create_mailbox(self, mailbox):
        self.conn.create_mailbox(mailbox)

    do_create_mailbox.add_argument('mailbox')

    @cmd_fn
    def do_delete_mailbox(self, mailbox):
        self.conn.delete_mailbox(mailbox)

    do_delete_mailbox.add_argument('mailbox')

    @cmd_fn
    def do_expunge(self):
        self.conn.expunge()

    def fmt_str(self, arg):
        if isinstance(arg, (bytes, bytearray)):
            arg = arg.decode('utf-8', errors='replace')
        elif not isinstance(arg, str):
            arg = str(arg)

        if not arg:
            return '""'

        for c in arg:
            if c.isspace():
                return repr(arg)
            if c in '"\'':
                return repr(arg)
            if c not in string.printable:
                return repr(arg)

        return arg

    def fmt_list(self, arg):
        return ' '.join(self.fmt_str(a) for a in arg)


def main():
    ap = argparse.ArgumentParser()

    config_group = ap.add_mutually_exclusive_group(required=True)
    config_group.add_argument('-c', '--config',
                              help='The AMT configuration file')
    config_group.add_argument('-s', '--server',
                              help='The server to connect to for testing')

    ap.add_argument('-u', '--user',
                    help='The username for connecting to the server')
    ap.add_argument('-S', '--no-ssl',
                    action='store_false', default=True,
                    dest='ssl', help='Do not use SSL')
    ap.add_argument('-P', '--password',
                    help='The password for connecting to the server')

    ap.add_argument('--clean', action='store_true', default=False,
                    help='Clean test mailboxes from the server')
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    if args.config:
        config = amt.config.load_config(args.config)
        account = config.default_account
    else:
        if args.user is None:
            ap.error('--user must be specified when not using a config file')
        if args.ssl:
            protocol = 'imaps'
        else:
            protocol = 'imap'
        account = amt.config.Account(server=args.server,
                                     user=args.user, protocol=protocol,
                                     password=args.password,
                                     password_fn=amt.config.get_password_input)

    account.prepare_password()

    shell = ImapShell(account)
    shell.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
