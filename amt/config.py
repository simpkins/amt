#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from __future__ import annotations

import errno
import getpass
import fcntl
import imp
import logging
import os
import pwd
import re
import struct
import sys
import tempfile
import time
from typing import Callable, Optional, List

from . import getpassword
from . import oauth2

IMAP_PORT = 143
IMAPS_PORT = 993
LDAP_PORT = 389
LDAPS_PORT = 636

DEFAULT_CFG_MODULES = ['accounts', 'classify', 'fetchmail', 'prune']


def _try_load_module(config, name):
    try:
        info = imp.find_module(name, [config.config_path])
    except ImportError:
        return
    module = imp.load_module('amt_config.' + name, *info)
    setattr(config, name, module)


def load_config(path, modules=None):
    path = expand_path(path)

    try:
        info = imp.find_module('__init__', [path])
    except ImportError:
        amt_config = imp.new_module('amt_config')
    else:
        amt_config = imp.load_module('amt_config', *info)
    sys.modules['amt_config'] = amt_config
    amt_config.config_path = path

    if modules is None:
        modules = DEFAULT_CFG_MODULES

    for mod in modules:
        _try_load_module(amt_config, mod)

    return amt_config


class Config:
    def __init__(self, config):
        self.config_dict = config

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


class ProtocolInfo:
    def __init__(self, protocol, port, ssl):
        self.protocol = protocol
        self.port = port
        self.ssl = ssl

    def resolve(self, supported_protocols):
        if self.protocol is None and self.port is None:
            raise Exception('no protocol and no port specified')
        if self.protocol is not None:
            for entry in supported_protocols:
                if self.protocol == entry.protocol:
                    break
            else:
                raise Exception('unsupported protocol %r' % (self.protocol,))
        else:
            for entry in supported_protocols:
                if self.port == entry.port:
                    break
            else:
                raise Exception('no protocol specified, and unknown port %r' %
                                (self.port,))

        if self.protocol is None:
            self.protocol = self.protocol or entry.protocol
        if self.port is None:
            self.port = entry.port
        if self.ssl is None:
            self.ssl = entry.ssl


class Account:
    SUPPORTED_PROTOCOLS = [
        ProtocolInfo('imaps', IMAPS_PORT, ssl=True),
        ProtocolInfo('imap', IMAP_PORT, ssl=False),
        ProtocolInfo('ldaps', LDAPS_PORT, ssl=False),
        ProtocolInfo('ldap', LDAP_PORT, ssl=True),
    ]
    SUPPORTED_AUTH_MECHANISMS = [
        "basic",
        "xoauth2",
    ]

    def __init__(
        self,
        server: str,
        user: str,
        protocol: Optional[str] = None,
        port: Optional[int] = None,
        password_fn: Optional[Callable[[Account], str]] = None,
        password: Optional[str] = None,
        ssl: Optional[bool] = None,
        auth: Optional[str] = None,
        oauth2_client_id: Optional[str] = None,
        oauth2_authority: Optional[str] = None,
        oath2_scopes: Optional[List[str]] = None,
    ) -> None:
        self.server = server

        self._protocol = ProtocolInfo(protocol, port, ssl)
        self._protocol.resolve(self.SUPPORTED_PROTOCOLS)

        if oauth2_client_id is not None:
            assert oauth2_authority is not None
            assert oath2_scopes is not None
            if auth is None:
                auth = "xoauth2"
            self.oauth2_client_id = oauth2_client_id
            self.oauth2_authority = oauth2_authority
            self.oath2_scopes = list(oath2_scopes)
        else:
            self.oauth2_client_id = None
            self.oauth2_authority = None
            self.oath2_scopes = None

        self._oauth2_fetcher = None
        if auth is None:
            self.auth = "basic"
        else:
            self.auth = auth.lower()
            if self.auth not in self.SUPPORTED_AUTH_MECHANISMS:
                raise ValueError(f"unsupported auth mechanism {auth!r}")

        self.user = user
        self._password = password
        self._password_fn = password_fn
        if self._password_fn is None:
            self._password_fn = get_password_keyring

    @property
    def protocol(self):
        return self._protocol.protocol

    @property
    def port(self):
        return self._protocol.port

    @property
    def ssl(self):
        return self._protocol.ssl

    @property
    def password(self):
        if self.auth != "basic":
            raise Exception('this account does not use basic '
                            'password authentication')

        if self._password is None:
            raise Exception('prepare_auth() must be called before '
                            'using the password field')
        return self._password

    def oauth2_token(self) -> bytes:
        if self.auth != "xoauth2":
            raise Exception("this account does not use OAuth")

        if self._oauth2_fetcher is None:
            raise Exception(
                "prepare_auth() must be called before attempting "
                "to use the OAuth 2 token"
            )

        return self._oauth2_fetcher.get_token()

    def _prepare_oauth2(self) -> None:
        if self._oauth2_fetcher is not None:
            return

        self._oauth2_fetcher = oauth2.TokenFetcher(
            username=self.user,
            client_id=self.oauth2_client_id,
            authority=self.oauth2_authority,
            scopes=self.oath2_scopes,
        )
        # Fetch the token now, even though we don't actually need it yet.
        # This ensures that if we need to prompt the user interactively that we
        # do it during the `prepare_auth()` stage, rather than waiting  until
        # we are actually attempting to log in.
        self._oauth2_fetcher.get_token()

    def prepare_auth(self) -> None:
        if self.auth == "basic":
            if self._password is None:
                self._password = self._password_fn(account=self)
        elif self.auth == "xoauth2":
            self._prepare_oauth2()
        else:
            raise Exception(f"unknown auth mechanism: {self.auth!r}")


class LockError(Exception):
    pass


class LockFile:
    LOCK_INFO_MSG = ('pid={pid}\n'
                     'acquire_time={acquire_time}\n')
    LOCK_INFO_PATTERN = (br'pid=(?P<pid>\d+)\n'
                         br'acquire_time=(?P<acquire_time>\d+(.\d*)?)\n')

    def __init__(self, path):
        self.path = path

        self.fd = None
        self.acquire()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()

    def __del__(self):
        if self.fd is not None:
            self.release()

    def acquire(self):
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self._try_acquire()
                return
            except LockError as ex:
                ex_msg = str(ex)

            # We couldn't acquire the lock file.
            # Check to see if it looks stale.
            if self._check_stale():
                # The lock looked stale, and _check_stale removed it.
                # Retry.
                continue

            raise LockError(ex_msg)

        raise LockError('failed to acquire lock %s after %d attempts' %
                        (self.path, max_attempts))

    def _try_acquire(self):
        try:
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                              0o644)
        except OSError as ex:
            if ex.errno == errno.EEXIST:
                raise LockError('failed to acquire lock: %s' % self.path)
            raise

        # Write info about the current process into the file
        info = self.LOCK_INFO_MSG.format(pid=os.getpid(),
                                         acquire_time=time.time())
        os.write(self.fd, info.encode('utf-8'))
        os.fsync(self.fd)

        # Acquire a lock on the file too.
        # This will help check for stale locks if the file already exists.
        fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _check_stale(self):
        # Since we may end up removing the file,
        # create a brief lockfile to ensure that no one else is trying to
        # remove the file at the same time.
        stale_lock_path = self.path + '.stale_check_lock'
        try:
            tmp_lock_fd = os.open(stale_lock_path,
                                  os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                  0o644)
        except:
            return False

        try:
            return self._check_stale_impl()
        finally:
            os.close(tmp_lock_fd)
            os.unlink(stale_lock_path)


    def _check_stale_impl(self):
        logging.debug('%s: checking for stale lock', self.path)
        try:
            fd = os.open(self.path, os.O_RDWR)
        except OSError as ex:
            if ex.errno == os.ENOENT:
                # Hmm, the file seems to have been removed since we
                # first tried to acquire it.  We can retry now.
                return True

        try:
            # Check to see if the file is locked.
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception as ex:
                logging.debug('%s: lock appears to be held: %s',
                              self.path, ex)
                return False

            # Read the file contents
            data = os.read(fd, 1024)
            m = re.match(self.LOCK_INFO_PATTERN, data)
            if not m:
                # We couldn't parse the file contents
                logging.debug('%s: unable to parse lockfile contents')
                return False

            pid = m.group('pid')
            acquire_time = m.group('acquire_time')
            # TODO: Check to see if the original owner process is still running

            # The lock looks stale
            logging.debug('%s: removing stale lock file')
            os.unlink(self.path)
            return True
        finally:
            os.close(fd)

    def release(self):
        if self.fd is None:
            raise Exception('attempted to release %s without holding '
                            'the lock' % self.path)
        os.unlink(self.path)
        os.close(self.fd)
        self.fd = None


def get_password_keyring(account: Account) -> str:
    return getpassword.get_password(
        user=account.user,
        server=account.server,
        port=account.port,
        protocol=account.protocol,
    )


def get_password_input(account: Account) -> str:
    prompt = 'Password for %s@%s: ' % (account.user, account.server)
    return getpass.getpass(prompt)


_cached_home_dir = None


def get_home_dir():
    global _cached_home_dir
    if _cached_home_dir is None:
        _cached_home_dir = compute_home_dir()
    return _cached_home_dir


def compute_home_dir():
    home_dir = os.environ.get('HOME')
    if home_dir is not None:
        return home_dir

    uid = os.geteuid()
    pwent = pwd.getpwuid(uid)
    return pwent.pw_dir


def expand_path(path):
    if path == '~':
        return get_home_dir()
    if path.startswith('~' + os.path.sep):
        return get_home_dir() + path[1:]
    return path


def default_maildb_path():
    return os.path.join(get_home_dir(), '.maildb')
