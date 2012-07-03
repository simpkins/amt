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
