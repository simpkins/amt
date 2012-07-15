#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import imp
import os

from . import getpassword


def load_config(path):
    # Import the configuration from the specified path
    # Always import it using the 'amt_config' module name, so that it
    # won't conflict with any system modules or any of our own module names.
    dirname, basename = os.path.split(path)
    info = imp.find_module(basename, [dirname])
    config = imp.load_module('amt_config', *info)
    return config


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
