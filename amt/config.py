#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import getpass
import imp
import os
import pwd

from . import getpassword
from .imap.constants import IMAP_PORT, IMAPS_PORT
from . import fetchmail


def load_config(path):
    params = {
        'Account': Account,
        'fetchmail': fetchmail,
    }

    with open(path, 'r') as f:
        data = f.read()
        exec(data, params, params)

    return Config(params)


class Config:
    def __init__(self, config):
        self.accounts = config['accounts']
        if 'default_account' in config:
            self._default_account = self.accounts[config['default_account']]
        elif len(self.accounts) == 1:
            self._default_account = next(iter(self.accounts.values()))
        else:
            self._default_account = None

    @property
    def default_account(self):
        if self._default_account is None:
            raise Exception('no default account')
        return self._default_account


class Account:
    def __init__(self, server, user,
                 protocol=None, port=None,
                 password_fn=None, password=None):
        self.server = server
        self.user = user
        self.protocol = protocol
        self.port = port
        self._password = password
        self._password_fn = password_fn

        if self.port is None:
            if self.protocol.lower() == 'imaps':
                self.port = IMAPS_PORT
            elif self.protocol.lower() == 'imap':
                self.port = IMAP_PORT

        if self._password_fn is None:
            self._password_fn = get_password_keyring

    @property
    def password(self):
        if self._password is None:
            raise Exception('prepare_password() must be called before '
                            'using the password field')
        return self._password

    def prepare_password(self):
        self._password = self._password_fn(account=self)


def get_password_keyring(account=None, server=None, user=None,
                         protocol=None, port=None):
    if user is None:
        user = account.user
    if server is None:
        server = account.server
    if protocol is None:
        protocol = account.protocol
    if port is None:
        port = account.port
    return getpassword.get_password(user=user, server=server,
                                    port=port, protocol=protocol)


def get_password_input(account=None, server=None, user=None,
                       protocol=None, port=None):
    if user is None:
        user = account.user
    if server is None:
        server = account.server
    prompt = 'Password for %s@%s: ' % (user, server)
    return getpass.getpass(prompt)


def get_home_dir():
    home_dir = os.environ.get('HOME')
    if home_dir is not None:
        return home_dir

    uid = os.geteuid()
    pwent = pwd.getpwuid(uid)
    return pwent.pw_dir


def default_maildb_path():
    return os.path.join(get_home_dir(), '.maildb')
