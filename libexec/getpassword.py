#!/usr/bin/python -tt
#
# Copyright (c) 2011, Adam Simpkins
#
import gnomekeyring as gkey

import getpass
import optparse
import os
import sys


class PasswordError(Exception):
    pass


class NoPasswordError(PasswordError):
    def __init__(self):
        PasswordError.__init__(self, 'no matching password found')


def get_password(**kwargs):
    try:
        ret = gkey.find_network_password_sync(**kwargs)
    except gkey.NoMatchError:
        raise NoPasswordError()
    except gkey.IOError:
        # Can't communicate with the gnome-keyring daemon
        # (For example, it isn't running, or the GNOME_KEYRING_CONTROL
        # environment variable isn't set.)
        raise PasswordError('unable to communicate with the gnome-keyring '
                            'daemon')

    if not ret:
        raise NoPasswordError()
    elif len(ret) != 1:
        raise PasswordError('expected exactly 1 password, found %d', len(ret))

    return ret[0].get('password')

def set_password(**kwargs):
    password = getpass.getpass('New password: ')

    gkey.set_network_password_sync(password=password, **kwargs)


def main():
    op = optparse.OptionParser()
    op.add_option('-u', '--user',
                  action='store',
                  help='The username')
    op.add_option('-s', '--server',
                  action='store',
                  help='The server')
    op.add_option('-p', '--port',
                  action='store', type='int',
                  help='The port number')
    op.add_option('-P', '--proto', '--protocol',
                  action='store', dest='protocol',
                  help='The port number')
    op.add_option('--set',
                  action='store_true', dest='set_password', default=False,
                  help='Set the password, rather than getting it')

    options, args = op.parse_args()

    if args:
        op.error('trailing arguments: %s' % ' '.join(args))

    params = ('user', 'server', 'port', 'protocol')
    kwargs = {}
    for p in params:
        value = getattr(options, p)
        if value is not None:
            kwargs[p] = value

    if options.set_password:
        set_password(**kwargs)
        return

    try:
        pw = get_password(**kwargs)
    except NoPasswordError as ex:
        print >> sys.stderr, 'error: no matching password found'
        return os.EX_UNAVAILABLE
    except PasswordError as ex:
        print >> sys.stderr, 'error:', ex
        return os.EX_DATAERR

    print(pw)
    return os.EX_OK


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
