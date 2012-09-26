#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import os
import pwd
import socket
import subprocess
import tempfile
import time

from amt import imap
from .util import random_string


class ImapServer:
    def __init__(self):
        self.cleanup_dir = True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.stop()

    def start(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix='amt_imap.')
        # dovecot complains if the directory is not world-readable
        os.chmod(self.tmpdir.name, 0o755)

        config_path = self._create_config()

        logging.debug('starting dovecot in %s', self.tmpdir.name)
        cmd = ['dovecot', '-F', '-c', config_path]
        self.process = subprocess.Popen(cmd, cwd=self.tmpdir.name)
        # Give dovecot time to start up and begin listening
        time.sleep(1)

        status = self.process.poll()
        if status is not None:
            raise Exception('dovecot failed to start: status=%s' % (status,))

    def get_account(self):
        account = imap.Account(server='127.0.0.1', port=self.port, ssl=False,
                               user='johndoe', password=self.password)
        return account

    def _create_config(self):
        config_path = os.path.join(self.tmpdir.name, 'dovecot.conf')

        parent_dir = os.path.dirname(os.path.dirname(__file__))
        tmpl_path = os.path.join(parent_dir, 'conf', 'dovecot.conf.tmpl')

        self.port = self._pick_port()
        self.password = random_string()
        params = {
            '@@base_dir@@': self.tmpdir.name,
            '@@user@@': self._get_system_user(),
            '@@port@@': str(self.port),
            '@@password@@': self.password,
        }
        self._process_template(tmpl_path, config_path, params)
        return config_path

    def _get_system_user(self):
        try:
            return os.environ['USER']
        except KeyError:
            pass

        uid = os.getuid()
        pwent = pwd.getpwuid(uid)
        return pwent.pw_name

    def _process_template(self, tmpl_path, out_path, params):
        with open(tmpl_path, 'r') as inf:
            with open(out_path, 'w') as outf:
                for line in inf:
                    for tmpl, value in params.items():
                        line = line.replace(tmpl, value)
                    outf.write(line)

    def _pick_port(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        addr = s.getsockname()
        s.close()
        return addr[1]

    def stop(self):
        self.process.terminate()
        self.process.wait()
        if self.cleanup_dir:
            self.tmpdir.cleanup()
        else:
            logging.debug('leaving dovecot directory %s', self.tmpdir.name)
            self.tmpdir.name = None
