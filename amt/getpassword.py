#!/usr/bin/python3 -tt
#
# Copyright (c) 2011, Adam Simpkins
#
import subprocess
import os

# The gnomekeyring module is only available for python 2.x
# Run a helper python 2.x program to get the password
HELPER_EXE = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          'libexec', 'getpassword.py'))


class PasswordError(Exception):
    pass


class NoPasswordError(PasswordError):
    def __init__(self):
        PasswordError.__init__(self, 'no matching password found')


def get_password(user=None, server=None, port=None, protocol=None):
    cmd = [HELPER_EXE]
    if user is not None:
        cmd.extend(['--user', user])
    if server is not None:
        cmd.extend(['--server', server])
    if port is not None:
        cmd.extend(['--port', str(port)])
    if protocol is not None:
        cmd.extend(['--protocol', protocol])

    cleanup_keyring_env()

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    code = p.returncode

    if code == os.EX_OK:
        if not out.endswith(b'\n'):
            raise PasswordError('expected output to end in a newline')
        return out[:-1].decode()

    if code == os.EX_UNAVAILABLE:
        raise NoPasswordError()
    raise PasswordError(err.strip())


def cleanup_keyring_env():
    # I haven't investigated too thoroughly, but the ubuntu login process
    # now seems to leave bogus info in GNOME_KEYRING_CONTROL.  (I'm guessing it
    # starts one keyring process, whose info ends up in the environment, then
    # later ends up killing the original process and starting a new one.)
    #
    # Unset GNOME_KEYRING_CONTROL if it looks like it contains bogus info.
    keyring_path = os.environ.get('GNOME_KEYRING_CONTROL')
    if keyring_path is None:
        return

    if not os.path.exists(keyring_path):
        del os.environ['GNOME_KEYRING_CONTROL']
